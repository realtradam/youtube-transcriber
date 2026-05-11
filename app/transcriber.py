import re

from requests import Session
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
    IpBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
)


class IPBlockedError(Exception):
    pass


class TranscriptNotAvailableError(Exception):
    pass


class TranscriptDisabledError(Exception):
    pass


class InvalidURLError(Exception):
    pass


_YOUTUBE_URL_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/embed/([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:https?://)?youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
]


def extract_video_id(url: str) -> str:
    for pattern in _YOUTUBE_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    raise InvalidURLError(f"Could not extract YouTube video ID from URL: {url}")


def create_api() -> YouTubeTranscriptApi:
    """Create a YouTubeTranscriptApi with a hardened browser-like Session."""
    session = Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.5",
        }
    )
    return YouTubeTranscriptApi(http_client=session)


def fetch_transcript_by_id(video_id: str, api: YouTubeTranscriptApi) -> list[dict]:
    """Fetch a transcript by video_id using a pre-built API instance."""
    try:
        transcript = api.fetch(video_id)
    except IpBlocked as e:
        raise IPBlockedError(f"YouTube is blocking requests from this IP. {e}")
    except VideoUnavailable:
        raise TranscriptNotAvailableError(f"Video {video_id} is unavailable")
    except TranscriptsDisabled:
        raise TranscriptDisabledError(
            f"Transcripts are disabled for video {video_id}"
        )
    except CouldNotRetrieveTranscript:
        raise TranscriptNotAvailableError(
            f"No transcript available for video {video_id}"
        )
    return transcript.to_raw_data()


def fetch_transcript(url: str) -> tuple[str, list[dict]]:
    video_id = extract_video_id(url)
    api = create_api()
    segments = fetch_transcript_by_id(video_id, api)
    return video_id, segments
