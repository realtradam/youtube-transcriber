import asyncio
import os

from app.storage import TranscriptStore


class TestTranscriptCache:
    def test_initialize_creates_database_file(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()
            assert os.path.exists(db_path), "Database file should exist after initialize"
            await store.close()

        asyncio.run(_run())

    def test_get_transcript_returns_none_when_not_found(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()
            result = await store.get_transcript("nonexistent_id")
            assert result is None
            await store.close()

        asyncio.run(_run())

    def test_save_and_retrieve_transcript(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()

            segments = [
                {"text": "hello", "start": 0.0, "duration": 1.0},
                {"text": "world", "start": 1.0, "duration": 1.0},
            ]
            await store.save_transcript(
                video_id="abc123",
                full_text="hello world",
                segments=segments,
            )

            result = await store.get_transcript("abc123")
            assert result is not None
            assert result["video_id"] == "abc123"
            assert result["full_text"] == "hello world"
            assert result["segments"] == segments
            assert isinstance(result["segments"], list)
            assert all(isinstance(s, dict) for s in result["segments"])

            await store.close()

        asyncio.run(_run())

    def test_save_transcript_overwrites_existing(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()

            await store.save_transcript(
                video_id="abc123",
                full_text="first version",
                segments=[],
            )
            await store.save_transcript(
                video_id="abc123",
                full_text="second version",
                segments=[],
            )

            result = await store.get_transcript("abc123")
            assert result is not None
            assert result["full_text"] == "second version"

            await store.close()

        asyncio.run(_run())

    def test_multiple_transcripts(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()

            await store.save_transcript(
                video_id="vid1",
                full_text="transcript one",
                segments=[{"text": "one", "start": 0.0, "duration": 1.0}],
            )
            await store.save_transcript(
                video_id="vid2",
                full_text="transcript two",
                segments=[{"text": "two", "start": 0.0, "duration": 1.0}],
            )

            result1 = await store.get_transcript("vid1")
            assert result1 is not None
            assert result1["video_id"] == "vid1"
            assert result1["full_text"] == "transcript one"

            result2 = await store.get_transcript("vid2")
            assert result2 is not None
            assert result2["video_id"] == "vid2"
            assert result2["full_text"] == "transcript two"

            await store.close()

        asyncio.run(_run())


class TestQueue:
    def _make_store(self, tmp_path):
        return TranscriptStore(db_path=os.path.join(str(tmp_path), "test.db"))

    def test_enqueue_creates_pending_entry(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            entry = await store.enqueue("vid_001")
            assert entry["video_id"] == "vid_001"
            assert entry["status"] == "pending"
            assert isinstance(entry["assigned_delay"], float)
            assert 30.0 <= entry["assigned_delay"] <= 60.0
            assert entry["error"] is None
            assert entry["error_type"] is None
            await store.close()
        asyncio.run(_run())

    def test_enqueue_duplicate_returns_existing(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            first = await store.enqueue("vid_001")
            second = await store.enqueue("vid_001")
            assert first["assigned_delay"] == second["assigned_delay"]
            assert first["id"] == second["id"]
            await store.close()
        asyncio.run(_run())

    def test_get_queue_entry(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            await store.enqueue("vid_001")
            entry = await store.get_queue_entry("vid_001")
            assert entry is not None
            assert entry["video_id"] == "vid_001"
            assert entry["status"] == "pending"
            assert await store.get_queue_entry("nonexistent") is None
            await store.close()
        asyncio.run(_run())

    def test_get_next_pending_returns_oldest_first(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            await store.enqueue("vid_001")
            await store.enqueue("vid_002")
            await store.enqueue("vid_003")
            first = await store.get_next_pending()
            assert first is not None
            assert first["video_id"] == "vid_001"
            assert first["status"] == "processing"
            assert first["started_at"] is not None
            second = await store.get_next_pending()
            assert second is not None
            assert second["video_id"] == "vid_002"
            await store.close()
        asyncio.run(_run())

    def test_get_next_pending_returns_none_when_empty(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            assert await store.get_next_pending() is None
            await store.close()
        asyncio.run(_run())

    def test_mark_completed_removes_entry(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            await store.enqueue("vid_001")
            await store.mark_completed("vid_001")
            assert await store.get_queue_entry("vid_001") is None
            await store.close()
        asyncio.run(_run())

    def test_mark_failed_updates_entry(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            await store.enqueue("vid_001")
            await store.mark_failed("vid_001", "IP was blocked", "ip_blocked")
            entry = await store.get_queue_entry("vid_001")
            assert entry is not None
            assert entry["status"] == "failed"
            assert entry["error"] == "IP was blocked"
            assert entry["error_type"] == "ip_blocked"
            await store.close()
        asyncio.run(_run())

    def test_get_position_and_estimate_for_pending(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            e1 = await store.enqueue("vid_001")
            e2 = await store.enqueue("vid_002")
            e3 = await store.enqueue("vid_003")
            result = await store.get_position_and_estimate("vid_003")
            assert result is not None
            assert result["position"] == 2
            expected = e1["assigned_delay"] + e2["assigned_delay"] + e3["assigned_delay"]
            assert abs(result["estimated_seconds"] - expected) < 0.01
            await store.close()
        asyncio.run(_run())

    def test_get_position_and_estimate_for_first_pending(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            e1 = await store.enqueue("vid_001")
            result = await store.get_position_and_estimate("vid_001")
            assert result is not None
            assert result["position"] == 0
            assert abs(result["estimated_seconds"] - e1["assigned_delay"]) < 0.01
            await store.close()
        asyncio.run(_run())

    def test_get_position_and_estimate_for_failed(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            await store.enqueue("vid_001")
            await store.mark_failed("vid_001", "error", "type")
            result = await store.get_position_and_estimate("vid_001")
            assert result == {"position": 0, "estimated_seconds": 0.0}
            await store.close()
        asyncio.run(_run())

    def test_get_position_and_estimate_not_found(self, tmp_path) -> None:
        async def _run() -> None:
            store = self._make_store(tmp_path)
            await store.initialize()
            assert await store.get_position_and_estimate("nonexistent") is None
            await store.close()
        asyncio.run(_run())
