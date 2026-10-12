import textwrap
import uuid
from pathlib import Path

from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings
from app.generation.base import GeneratorInterface, ProgressCallback
from app.generation.gemini_client import BACKGROUND_TRANSIENT_SERVER_RETRIES, complete_json
from app.generation.json_utils import parse_json_response
from app.generation.pollinations_image import generate_unique_image
from app.generation.text_combine import combine_source_text
from app.generation.tts import synthesize_narration
from app.models.chat import Chat
from app.models.material_source import MaterialSource

SYSTEM_PROMPT = """You are creating a short explainer video that teaches study material to a curious \
viewer, scene by scene. Given study material (possibly from multiple sources), produce a JSON object with:
- "scenes": a list of 5-7 scenes that walk through the material in order, building up the full \
explanation by the end. Each scene is an object with:
  - "key_subject": a short, CONCRETE noun phrase (3-8 words) naming the single most important object, \
diagram, or process this scene depicts, using the EXACT terminology from the source material — not a vague \
paraphrase. Examples: "the magma chamber beneath a volcano", "a chloroplast inside a leaf cell", "a worker \
bee's pollen basket (corbicula)", "the French National Assembly in 1789". This is the literal subject the \
artist must draw — be as specific and factual as the material allows.
  - "scene_description": a CONCRETE, LITERAL visual description that expands on key_subject — name the \
actual things from the material, not generic decorative scenery. State the art style explicitly: "flat 2D \
cartoon illustration, like a children's educational picture book, with simple bold outlines and flat \
colors". Include 1-2 recurring simple characters doing/pointing at something relevant. Do NOT mention any \
text, words, letters, captions, or speech bubbles in this description — describe only the visual scene, \
captions are added separately afterward.
  - "narration": ONE spoken sentence (under 22 words) that a narrator says out loud while this scene is \
on screen. This is where the teaching content goes — each scene's narration should add a new piece of \
information, written as natural spoken language (not a list, not a heading, no markdown). By the final \
scene, the full concept should have been explained.

Keep a consistent cast of 1-2 simple, fun recurring characters across all scenes so the video reads as one \
continuous story.

Respond with ONLY the JSON object, no markdown fences, no commentary."""

IMAGE_PROMPT_PREFIX = (
    "Flat 2D cartoon illustration in the style of a children's educational picture book, simple bold outlines "
    "and flat colors. Single scene only (not a grid or collage of multiple images), no text, no letters, no "
    "writing anywhere in the image. The main subject, drawn clearly and centrally: "
)

FRAME_SIZE = 768
CROSSFADE_SECONDS = 0.6
MIN_SCENE_SECONDS = 3.0
SCENE_PADDING_SECONDS = 0.6

CAPTION_FONT_CANDIDATES = ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]
CAPTION_FONT_SIZE = 30
CAPTION_MAX_CHARS_PER_LINE = 40


class VideoGenerator(GeneratorInterface):
    mode = "video"
    supports_progress = True

    def generate(
        self,
        chat: Chat,
        sources: list[MaterialSource],
        options: dict | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        text = combine_source_text(sources)
        if not text.strip():
            raise ValueError("This chat has no extracted source text to generate from.")

        raw = complete_json(SYSTEM_PROMPT, text, max_retries=BACKGROUND_TRANSIENT_SERVER_RETRIES)
        script = parse_json_response(raw)
        scenes = script.get("scenes") or []
        if not scenes:
            raise ValueError("No video scenes were generated.")

        settings = get_settings()
        video_id = str(uuid.uuid4())
        work_dir = Path(settings.generated_dir) / "videos" / video_id
        work_dir.mkdir(parents=True, exist_ok=True)

        total_steps = len(scenes) + 1  # +1 for the final compile step, so the bar doesn't stall at 100%
        clips = []
        scene_meta = []
        seen_image_hashes: set[str] = set()
        for i, scene in enumerate(scenes):
            key_subject = (scene.get("key_subject") or "").strip()
            description = (scene.get("scene_description") or "").strip()
            narration = (scene.get("narration") or "").strip()
            if description and narration:
                frame_path = work_dir / f"scene_{i}.jpg"
                audio_path = work_dir / f"scene_{i}.mp3"

                # key_subject leads the prompt (diffusion models weight earlier tokens more
                # heavily) so the exact, material-grounded subject anchors the image instead of
                # getting diluted by the more narrative scene_description that follows.
                subject_prefix = f"{key_subject}. " if key_subject else ""
                generate_unique_image(
                    f"{IMAGE_PROMPT_PREFIX}{subject_prefix}{description}",
                    frame_path,
                    seen_image_hashes,
                    size=FRAME_SIZE,
                )
                _burn_caption(frame_path, narration)
                narration_seconds = synthesize_narration(narration, audio_path)

                scene_seconds = max(narration_seconds + SCENE_PADDING_SECONDS, MIN_SCENE_SECONDS)
                image_clip = ImageClip(str(frame_path)).set_duration(scene_seconds)
                audio_clip = AudioFileClip(str(audio_path))
                clip = image_clip.set_audio(audio_clip)
                if clips:
                    clip = clip.crossfadein(CROSSFADE_SECONDS)
                clips.append(clip)
                scene_meta.append({"narration": narration, "duration": scene_seconds})

            if on_progress:
                on_progress(i + 1, total_steps)

        if not clips:
            raise ValueError("No usable video scenes were generated (missing images or narration).")

        padding = -CROSSFADE_SECONDS if len(clips) > 1 else 0
        final = concatenate_videoclips(clips, method="compose", padding=padding)
        video_path = work_dir / "video.mp4"
        final.write_videofile(
            str(video_path),
            fps=24,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(work_dir / "temp-audio.m4a"),
            remove_temp=True,
            logger=None,
        )
        for clip in clips:
            clip.close()
        final.close()

        if on_progress:
            on_progress(total_steps, total_steps)

        return {"video_url": f"/media/videos/{video_id}/video.mp4", "scenes": scene_meta}


def _load_caption_font() -> ImageFont.FreeTypeFont:
    for path in CAPTION_FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, CAPTION_FONT_SIZE)
    return ImageFont.load_default()


def _burn_caption(image_path: Path, text: str) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    font = _load_caption_font()
    lines = textwrap.wrap(text, width=CAPTION_MAX_CHARS_PER_LINE) or [text]

    line_height = font.getbbox("Ag")[3] + 10
    band_height = line_height * len(lines) + 24
    width, height = image.size
    draw.rectangle([0, height - band_height, width, height], fill=(0, 0, 0, 165))

    y = height - band_height + 12
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) / 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height

    image.save(image_path, quality=90)
