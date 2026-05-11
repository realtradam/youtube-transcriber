from unittest.mock import patch

import pytest
from youtube_transcript_api._errors import IpBlocked, TranscriptsDisabled

from app.transcriber import (
    InvalidURLError,
    IPBlockedError,
    TranscriptDisabledError,
    create_api,
    extract_video_id,
    fetch_transcript_by_id,
)


class TestExtractVideoId:
    def test_standard_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self) -> None:
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_no_protocol(self) -> None:
        assert extract_video_id("youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url(self) -> None:
        try:
            extract_video_id("https://example.com/video")
            assert False, "Expected InvalidURLError"
        except InvalidURLError:
            pass


class TestCreateApi:
    def test_create_api_has_browser_user_agent(self) -> None:
        api = create_api()
        # The session is stored on the fetcher inside the API instance.
        session = api._fetcher._http_client
        ua = session.headers.get("User-Agent", "")
        assert "Chrome" in ua


class TestFetchTranscriptById:
    def test_fetch_transcript_by_id_raises_ip_blocked(self) -> None:
        api = create_api()
        with patch.object(api, "fetch", side_effect=IpBlocked(video_id="test")):
            with pytest.raises(IPBlockedError):
                fetch_transcript_by_id("test", api)

    def test_fetch_transcript_by_id_raises_transcript_disabled(self) -> None:
        api = create_api()
        with patch.object(api, "fetch", side_effect=TranscriptsDisabled(video_id="test")):
            with pytest.raises(TranscriptDisabledError):
                fetch_transcript_by_id("test", api)
