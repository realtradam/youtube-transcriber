import asyncio

from youtube_transcript_api import YouTubeTranscriptApi

from app.storage import TranscriptStore
from app.transcriber import (
    IPBlockedError,
    TranscriptDisabledError,
    TranscriptNotAvailableError,
    fetch_transcript_by_id,
)


async def process_next(store: TranscriptStore, api: YouTubeTranscriptApi) -> bool:
    """Process the next pending queue item. Returns True if one was processed."""
    entry = await store.get_next_pending()
    if entry is None:
        return False

    video_id = entry["video_id"]

    try:
        try:
            segments = await asyncio.to_thread(fetch_transcript_by_id, video_id, api)
        except IPBlockedError as e:
            await store.mark_failed(video_id, str(e), "ip_blocked")
            return True
        except TranscriptNotAvailableError as e:
            await store.mark_failed(video_id, str(e), "not_available")
            return True
        except TranscriptDisabledError as e:
            await store.mark_failed(video_id, str(e), "transcript_disabled")
            return True
        except Exception as e:
            await store.mark_failed(video_id, str(e), "internal_error")
            return True

        full_text = " ".join(s["text"] for s in segments)
        await store.save_transcript(video_id, full_text, segments)
        await store.mark_completed(video_id)
        return True
    finally:
        await asyncio.sleep(entry["assigned_delay"])


async def run_worker(
    store: TranscriptStore,
    api: YouTubeTranscriptApi,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the queue worker loop until shutdown_event is set."""
    while not shutdown_event.is_set():
        processed = await process_next(store, api)
        if not processed:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
