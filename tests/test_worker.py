import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

from app.storage import TranscriptStore
from app.transcriber import (
    IPBlockedError,
    TranscriptDisabledError,
)
from app.worker import process_next


def _to_thread_passthrough(func, *args, **kwargs):
    """Replacement for asyncio.to_thread that runs the function synchronously."""

    async def _coro():
        return func(*args, **kwargs)

    return _coro()


def _patch_to_thread():
    return patch("app.worker.asyncio.to_thread", new=_to_thread_passthrough)


class TestProcessNext:
    def test_process_next_returns_false_when_queue_empty(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()

            with patch("app.worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                api = MagicMock()
                result = await process_next(store, api)
                assert result is False
                mock_sleep.assert_not_called()

            await store.close()

        asyncio.run(_run())

    def test_process_next_success(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()
            entry = await store.enqueue("vid_001")

            with patch("app.worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
                 _patch_to_thread(), \
                 patch("app.worker.fetch_transcript_by_id", return_value=[{"text": "hello", "start": 0.0, "duration": 1.0}]):
                api = MagicMock()
                result = await process_next(store, api)
                assert result is True
                mock_sleep.assert_called_once()
                slept_for = mock_sleep.call_args.args[0]
                assert 30.0 <= slept_for <= 60.0
                assert abs(slept_for - entry["assigned_delay"]) < 0.001

            transcript = await store.get_transcript("vid_001")
            assert transcript is not None
            assert transcript["full_text"] == "hello"
            assert await store.get_queue_entry("vid_001") is None
            await store.close()

        asyncio.run(_run())

    def test_process_next_ip_blocked(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()
            await store.enqueue("vid_001")

            with patch("app.worker.asyncio.sleep", new_callable=AsyncMock), \
                 _patch_to_thread(), \
                 patch("app.worker.fetch_transcript_by_id", side_effect=IPBlockedError("blocked")):
                api = MagicMock()
                result = await process_next(store, api)
                assert result is True

            entry = await store.get_queue_entry("vid_001")
            assert entry is not None
            assert entry["status"] == "failed"
            assert entry["error_type"] == "ip_blocked"
            assert await store.get_transcript("vid_001") is None
            await store.close()

        asyncio.run(_run())

    def test_process_next_transcript_disabled(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()
            await store.enqueue("vid_001")

            with patch("app.worker.asyncio.sleep", new_callable=AsyncMock), \
                 _patch_to_thread(), \
                 patch("app.worker.fetch_transcript_by_id", side_effect=TranscriptDisabledError("disabled")):
                api = MagicMock()
                result = await process_next(store, api)
                assert result is True

            entry = await store.get_queue_entry("vid_001")
            assert entry is not None
            assert entry["status"] == "failed"
            assert entry["error_type"] == "transcript_disabled"
            await store.close()

        asyncio.run(_run())

    def test_process_next_downloads_before_sleeping(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()
            await store.enqueue("vid_001")

            call_order = []

            async def mock_sleep(seconds):
                call_order.append("sleep")

            def mock_fetch(video_id, api):
                call_order.append("fetch")
                return [{"text": "hello", "start": 0.0, "duration": 1.0}]

            with patch("app.worker.asyncio.sleep", side_effect=mock_sleep), \
                 _patch_to_thread(), \
                 patch("app.worker.fetch_transcript_by_id", side_effect=mock_fetch):
                api = MagicMock()
                result = await process_next(store, api)
                assert result is True

            assert call_order == ["fetch", "sleep"]
            await store.close()

        asyncio.run(_run())

    def test_process_next_sleeps_after_error(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()
            entry = await store.enqueue("vid_001")

            with patch("app.worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
                 _patch_to_thread(), \
                 patch("app.worker.fetch_transcript_by_id", side_effect=IPBlockedError("blocked")):
                api = MagicMock()
                result = await process_next(store, api)
                assert result is True
                mock_sleep.assert_called_once()
                slept_for = mock_sleep.call_args.args[0]
                assert abs(slept_for - entry["assigned_delay"]) < 0.001

            entry = await store.get_queue_entry("vid_001")
            assert entry is not None
            assert entry["status"] == "failed"
            await store.close()

        asyncio.run(_run())

    def test_process_next_sleeps_after_error_before_next_download(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()
            await store.enqueue("vid_001")

            call_order = []

            async def mock_sleep(seconds):
                call_order.append("sleep")

            def mock_fetch(video_id, api):
                call_order.append("fetch")
                raise IPBlockedError("blocked")

            with patch("app.worker.asyncio.sleep", side_effect=mock_sleep), \
                 _patch_to_thread(), \
                 patch("app.worker.fetch_transcript_by_id", side_effect=mock_fetch):
                api = MagicMock()
                await process_next(store, api)

            assert call_order == ["fetch", "sleep"]
            await store.close()

        asyncio.run(_run())

    def test_process_next_no_sleep_before_first_download_after_empty_queue(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()

            call_order = []

            async def mock_sleep(seconds):
                call_order.append("sleep")

            def mock_fetch(video_id, api):
                call_order.append("fetch")
                return [{"text": "hello", "start": 0.0, "duration": 1.0}]

            with patch("app.worker.asyncio.sleep", side_effect=mock_sleep), \
                 _patch_to_thread(), \
                 patch("app.worker.fetch_transcript_by_id", side_effect=mock_fetch):
                api = MagicMock()

                # Queue is empty — no sleep, no fetch
                result = await process_next(store, api)
                assert result is False
                assert call_order == []

                # Video is added while queue was idle
                await store.enqueue("vid_001")

                # Next call downloads immediately, then sleeps after
                result = await process_next(store, api)
                assert result is True
                assert call_order == ["fetch", "sleep"]

            await store.close()

        asyncio.run(_run())

    def test_process_next_processes_fifo_order(self, tmp_path) -> None:
        async def _run() -> None:
            db_path = os.path.join(str(tmp_path), "test.db")
            store = TranscriptStore(db_path=db_path)
            await store.initialize()
            await store.enqueue("vid_001")
            await store.enqueue("vid_002")

            with patch("app.worker.asyncio.sleep", new_callable=AsyncMock), \
                 _patch_to_thread(), \
                 patch("app.worker.fetch_transcript_by_id", return_value=[{"text": "first", "start": 0.0, "duration": 1.0}]):
                api = MagicMock()
                await process_next(store, api)

            assert (await store.get_transcript("vid_001")) is not None
            assert (await store.get_transcript("vid_002")) is None
            assert (await store.get_queue_entry("vid_002")) is not None
            await store.close()

        asyncio.run(_run())
