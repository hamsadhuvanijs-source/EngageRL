import re

from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

VIDEO_ID_PATTERN = re.compile(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})")


def parse_video_id(url: str) -> str | None:
    match = VIDEO_ID_PATTERN.search(url)
    return match.group(1) if match else None


def extract_youtube(url: str) -> tuple[str, str]:
    video_id = parse_video_id(url)
    if not video_id:
        raise ValueError("Could not find a YouTube video ID in that URL.")

    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id)
    except (TranscriptsDisabled, NoTranscriptFound) as exc:
        raise ValueError("This video has no available transcript/captions.") from exc
    except Exception as exc:
        # youtube-transcript-api scrapes an undocumented YouTube endpoint that some
        # networks/IPs (datacenters, some corporate/VPN egress) get blocked from,
        # which surfaces as a raw XML parse error rather than a clean library exception.
        raise ValueError(
            "Could not fetch this video's transcript. This can happen if YouTube is blocking "
            "transcript requests from your network — try again from a different network, or "
            "paste the transcript text in as a source instead."
        ) from exc

    text = " ".join(segment["text"] for segment in segments).strip()
    if not text:
        raise ValueError("This video's transcript was empty.")

    label = f"YouTube: {video_id}"
    return text, label
