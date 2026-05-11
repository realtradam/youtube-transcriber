import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from httpx import ASGITransport

import app.main as main_module
from app.main import app
from app.storage import TranscriptStore


def _run_with_app(tmp_path, coro_factory):
    """Initialize app lifespan with a temp-DB store, run coro_factory(client, store), tear down."""

    async def _runner():
        db_path = os.path.join(str(tmp_path), "test.db")

        def _store_factory(_path):
            return TranscriptStore(db_path=db_path)

        with patch.object(main_module, "run_worker", new=AsyncMock()), \
             patch.object(main_module, "create_api", new=MagicMock()), \
             patch.object(main_module, "TranscriptStore", side_effect=_store_factory):
            async with main_module.lifespan(app):
                transport = ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    await coro_factory(client, app.state.store)

    asyncio.run(_runner())


class TestGetTranscript:
    def test_health(self, tmp_path) -> None:
        async def _do(client, store):
            r = await client.get("/health")
            assert r.status_code == 200
            assert r.json() == {"status": "ok"}

        _run_with_app(tmp_path, _do)

    def test_invalid_url_returns_400(self, tmp_path) -> None:
        async def _do(client, store):
            r = await client.get("/api/transcript", params={"url": "https://example.com/notavideo"})
            assert r.status_code == 400
            assert "Invalid" in r.json()["detail"]

        _run_with_app(tmp_path, _do)

    def test_missing_url_returns_422(self, tmp_path) -> None:
        async def _do(client, store):
            r = await client.get("/api/transcript")
            assert r.status_code == 422

        _run_with_app(tmp_path, _do)

    def test_new_video_returns_queued(self, tmp_path) -> None:
        async def _do(client, store):
            r = await client.get(
                "/api/transcript",
                params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "queued"
            assert body["video_id"] == "dQw4w9WgXcQ"
            assert isinstance(body["estimated_seconds"], (int, float))
            assert body["estimated_seconds"] > 0

        _run_with_app(tmp_path, _do)

    def test_cached_video_returns_completed(self, tmp_path) -> None:
        async def _do(client, store):
            await store.save_transcript(
                "dQw4w9WgXcQ",
                "hello world",
                [{"text": "hello world", "start": 0.0, "duration": 1.0}],
            )
            r = await client.get(
                "/api/transcript",
                params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "completed"
            assert body["full_text"] == "hello world"
            assert isinstance(body["segments"], list)
            assert len(body["segments"]) == 1

        _run_with_app(tmp_path, _do)

    def test_already_queued_video_returns_existing_status(self, tmp_path) -> None:
        async def _do(client, store):
            await store.enqueue("dQw4w9WgXcQ")
            r = await client.get(
                "/api/transcript",
                params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "queued"
            assert body["video_id"] == "dQw4w9WgXcQ"

            r2 = await client.get(
                "/api/transcript",
                params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert r2.status_code == 200
            assert r2.json()["video_id"] == "dQw4w9WgXcQ"

        _run_with_app(tmp_path, _do)

    def test_failed_video_returns_failure(self, tmp_path) -> None:
        async def _do(client, store):
            await store.enqueue("dQw4w9WgXcQ")
            await store.mark_failed("dQw4w9WgXcQ", "Transcripts disabled", "transcript_disabled")
            r = await client.get(
                "/api/transcript",
                params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "failed"
            assert body["error_type"] == "transcript_disabled"

        _run_with_app(tmp_path, _do)
