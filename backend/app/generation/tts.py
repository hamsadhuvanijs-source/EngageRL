import asyncio
import time
from pathlib import Path

import edge_tts
from moviepy.editor import AudioFileClip

# edge-tts drives Microsoft Edge's read-aloud voices over a free, keyless websocket API.
VOICE = "en-US-AriaNeural"

# Same class of transient-network problem as the Gemini/Pollinations calls (a DNS blip surfaces
# here as a raw OSError — e.g. "[Errno 11001] getaddrinfo failed" on Windows — since this is a
# bare websocket call with no retry logic of its own) — worth a few quick retries rather than
# failing a whole video generation over one scene's narration.
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0


def synthesize_narration(text: str, dest: Path, voice: str = VOICE) -> float:
    """Synthesizes narration audio for one scene and returns its duration in seconds so the
    frame can be timed to match. Runs its own asyncio event loop — safe to call from a plain
    background thread since edge-tts and moviepy don't need one already running."""

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(dest))

    for attempt in range(MAX_RETRIES):
        try:
            asyncio.run(_run())
            break
        except OSError:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise

    with AudioFileClip(str(dest)) as clip:
        return clip.duration
