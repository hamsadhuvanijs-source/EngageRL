import asyncio
from pathlib import Path

import edge_tts
from moviepy.editor import AudioFileClip

# edge-tts drives Microsoft Edge's read-aloud voices over a free, keyless websocket API.
VOICE = "en-US-AriaNeural"


def synthesize_narration(text: str, dest: Path, voice: str = VOICE) -> float:
    """Synthesizes narration audio for one scene and returns its duration in seconds so the
    frame can be timed to match. Runs its own asyncio event loop — safe to call from a plain
    background thread since edge-tts and moviepy don't need one already running."""

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(dest))

    asyncio.run(_run())

    with AudioFileClip(str(dest)) as clip:
        return clip.duration
