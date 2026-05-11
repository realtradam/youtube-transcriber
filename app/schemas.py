from typing import Literal

from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    text: str
    start: float
    duration: float


class TranscriptResultResponse(BaseModel):
    status: Literal["completed"] = "completed"
    video_id: str
    full_text: str
    segments: list[TranscriptSegment]


class TranscriptQueuedResponse(BaseModel):
    status: Literal["queued", "processing"]
    video_id: str
    position: int
    estimated_seconds: float


class TranscriptFailedResponse(BaseModel):
    status: Literal["failed"] = "failed"
    video_id: str
    error: str
    error_type: str


TranscriptResponse = (
    TranscriptResultResponse | TranscriptQueuedResponse | TranscriptFailedResponse
)
