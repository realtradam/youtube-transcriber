import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.schemas import (
    TranscriptFailedResponse,
    TranscriptQueuedResponse,
    TranscriptResponse,
    TranscriptResultResponse,
    TranscriptSegment,
)
from app.storage import TranscriptStore
from app.transcriber import InvalidURLError, create_api, extract_video_id
from app.worker import run_worker

from datetime import datetime

# How long to wait before retrying a failed video, per error_type (seconds).
# All failures are retryable; cooldowns avoid hammering YouTube or a blocked IP.
RETRY_COOLDOWN_SECONDS: dict[str, float] = {
    "not_available": 120.0,        # subtitles may not be generated yet
    "transcript_disabled": 120.0,  # rarely changes, but allow eventual recheck
    "ip_blocked": 120.0,           # back off when our IP is blocked
    "internal_error": 120.0,       # transient bugs / network blips
}
DEFAULT_RETRY_COOLDOWN_SECONDS = 120.0


def _failed_entry_is_retryable(entry: dict) -> bool:
    """Return True if a failed queue entry has cooled down enough to retry."""
    cooldown = RETRY_COOLDOWN_SECONDS.get(
        entry["error_type"] or "", DEFAULT_RETRY_COOLDOWN_SECONDS
    )
    updated_at = entry.get("updated_at")
    if not updated_at:
        return True
    age = (datetime.utcnow() - datetime.fromisoformat(updated_at)).total_seconds()
    return age >= cooldown


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = TranscriptStore("data/transcripts.db")
    await store.initialize()
    api = create_api()
    shutdown_event = asyncio.Event()
    worker_task = asyncio.create_task(run_worker(store, api, shutdown_event))
    app.state.store = store
    try:
        yield
    finally:
        shutdown_event.set()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await store.close()


app = FastAPI(
    title="YouTube Transcriber",
    description="API for fetching YouTube video transcripts",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/transcript", response_model=TranscriptResponse)
async def get_transcript(
    request: Request,
    url: str = Query(..., description="YouTube video URL", min_length=1),
) -> TranscriptResponse:
    try:
        video_id = extract_video_id(url)
    except InvalidURLError:
        raise HTTPException(status_code=400, detail=f"Invalid YouTube URL: {url}")

    store: TranscriptStore = request.app.state.store

    cached = await store.get_transcript(video_id)
    if cached is not None:
        return TranscriptResultResponse(
            video_id=cached["video_id"],
            full_text=cached["full_text"],
            segments=[TranscriptSegment(**s) for s in cached["segments"]],
        )

    entry = await store.get_queue_entry(video_id)
    if entry is not None:
        if entry["status"] == "failed":
            # All failures are retryable once their cooldown has elapsed.
            if _failed_entry_is_retryable(entry):
                await store.requeue_failed(video_id)
                estimate = await store.get_position_and_estimate(video_id)
                return TranscriptQueuedResponse(
                    status="queued",
                    video_id=video_id,
                    position=estimate["position"],
                    estimated_seconds=estimate["estimated_seconds"],
                )
            return TranscriptFailedResponse(
                video_id=video_id,
                error=entry["error"] or "",
                error_type=entry["error_type"] or "",
            )
        # pending or processing
        estimate = await store.get_position_and_estimate(video_id)
        api_status = "processing" if entry["status"] == "processing" else "queued"
        return TranscriptQueuedResponse(
            status=api_status,
            video_id=video_id,
            position=estimate["position"],
            estimated_seconds=estimate["estimated_seconds"],
        )

    # Not cached and not queued — enqueue it.
    await store.enqueue(video_id)
    estimate = await store.get_position_and_estimate(video_id)
    return TranscriptQueuedResponse(
        status="queued",
        video_id=video_id,
        position=estimate["position"],
        estimated_seconds=estimate["estimated_seconds"],
    )
