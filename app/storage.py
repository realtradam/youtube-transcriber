import aiosqlite
import json
import os
import random
from datetime import datetime


class TranscriptStore:
    """Persists cached transcripts in SQLite."""

    def __init__(self, db_path: str = "data/transcripts.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create the database directory, open the connection, and ensure the table exists."""
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """CREATE TABLE IF NOT EXISTS transcripts (
                video_id TEXT PRIMARY KEY,
                full_text TEXT NOT NULL,
                segments TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        await self._db.execute(
            """CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                assigned_delay REAL NOT NULL,
                error TEXT,
                error_type TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT
            )"""
        )
        await self._db.commit()

    async def get_transcript(self, video_id: str) -> dict | None:
        """Retrieve a cached transcript by video_id, or None if not found."""
        cursor = await self._db.execute(
            "SELECT video_id, full_text, segments, created_at FROM transcripts WHERE video_id = ?",
            (video_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "video_id": row[0],
            "full_text": row[1],
            "segments": json.loads(row[2]),
        }

    async def save_transcript(
        self, video_id: str, full_text: str, segments: list[dict]
    ) -> None:
        """Insert or replace a transcript row."""
        await self._db.execute(
            """INSERT OR REPLACE INTO transcripts (video_id, full_text, segments, created_at)
               VALUES (?, ?, ?, ?)""",
            (video_id, full_text, json.dumps(segments), datetime.utcnow().isoformat()),
        )
        await self._db.commit()

    async def enqueue(self, video_id: str) -> dict:
        """Add a video to the queue (no-op if already queued). Returns the queue entry."""
        delay = random.uniform(30.0, 60.0)
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """INSERT OR IGNORE INTO queue
               (video_id, status, assigned_delay, error, error_type, created_at, updated_at, started_at)
               VALUES (?, 'pending', ?, NULL, NULL, ?, ?, NULL)""",
            (video_id, delay, now, now),
        )
        await self._db.commit()
        cursor = await self._db.execute(
            "SELECT id, video_id, status, assigned_delay, error, error_type, created_at, updated_at, started_at FROM queue WHERE video_id = ?",
            (video_id,),
        )
        row = await cursor.fetchone()
        return {
            "id": row[0], "video_id": row[1], "status": row[2],
            "assigned_delay": row[3], "error": row[4], "error_type": row[5],
            "created_at": row[6], "updated_at": row[7], "started_at": row[8],
        }

    async def get_queue_entry(self, video_id: str) -> dict | None:
        """Return the queue entry for a video, or None if not queued."""
        cursor = await self._db.execute(
            "SELECT id, video_id, status, assigned_delay, error, error_type, created_at, updated_at, started_at FROM queue WHERE video_id = ?",
            (video_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "video_id": row[1], "status": row[2],
            "assigned_delay": row[3], "error": row[4], "error_type": row[5],
            "created_at": row[6], "updated_at": row[7], "started_at": row[8],
        }

    async def get_next_pending(self) -> dict | None:
        """Atomically claim the next pending queue entry and mark it as processing."""
        cursor = await self._db.execute(
            "SELECT id, video_id, status, assigned_delay, error, error_type, created_at, updated_at, started_at FROM queue WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            "UPDATE queue SET status = 'processing', started_at = ?, updated_at = ? WHERE video_id = ?",
            (now, now, row[1]),
        )
        await self._db.commit()
        return {
            "id": row[0], "video_id": row[1], "status": "processing",
            "assigned_delay": row[3], "error": row[4], "error_type": row[5],
            "created_at": row[6], "updated_at": now, "started_at": now,
        }

    async def mark_completed(self, video_id: str) -> None:
        """Remove the queue entry for a completed video."""
        await self._db.execute("DELETE FROM queue WHERE video_id = ?", (video_id,))
        await self._db.commit()

    async def mark_failed(self, video_id: str, error: str, error_type: str) -> None:
        """Mark a queue entry as failed with an error message and type."""
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            "UPDATE queue SET status = 'failed', error = ?, error_type = ?, updated_at = ? WHERE video_id = ?",
            (error, error_type, now, video_id),
        )
        await self._db.commit()

    async def requeue_failed(self, video_id: str) -> dict:
        """Reset a failed queue entry back to pending so it will be retried.

        Assigns a fresh delay and clears the previous error. Returns the entry.
        """
        delay = random.uniform(30.0, 60.0)
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """UPDATE queue
               SET status = 'pending', assigned_delay = ?, error = NULL,
                   error_type = NULL, updated_at = ?, started_at = NULL
               WHERE video_id = ? AND status = 'failed'""",
            (delay, now, video_id),
        )
        await self._db.commit()
        return await self.get_queue_entry(video_id)

    async def get_position_and_estimate(self, video_id: str) -> dict | None:
        """Return queue position (1-indexed) and estimated wait seconds for a video."""
        entry = await self.get_queue_entry(video_id)
        if entry is None:
            return None
        if entry["status"] == "failed":
            return {"position": 0, "estimated_seconds": 0.0}
        now = datetime.utcnow()
        if entry["status"] == "processing":
            elapsed = (now - datetime.fromisoformat(entry["started_at"])).total_seconds()
            remaining = max(0.0, entry["assigned_delay"] - elapsed)
            return {"position": 0, "estimated_seconds": remaining}
        # pending
        cursor = await self._db.execute(
            "SELECT status, assigned_delay, started_at FROM queue WHERE status IN ('pending', 'processing') AND id < ? ORDER BY id ASC",
            (entry["id"],),
        )
        rows = await cursor.fetchall()
        total_wait = 0.0
        for r in rows:
            if r[0] == "processing":
                elapsed = (now - datetime.fromisoformat(r[2])).total_seconds()
                total_wait += max(0.0, r[1] - elapsed)
            else:
                total_wait += r[1]
        total_wait += entry["assigned_delay"]
        position = len(rows)
        return {"position": position, "estimated_seconds": total_wait}

    async def close(self) -> None:
        """Close the database connection if it is open."""
        if self._db is not None:
            await self._db.close()
            self._db = None
