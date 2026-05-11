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
