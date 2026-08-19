import uuid
from pathlib import Path

from app.config import get_settings
from app.generation.base import GeneratorInterface, ProgressCallback
from app.generation.gemini_client import BACKGROUND_TRANSIENT_SERVER_RETRIES, complete_json
from app.generation.json_utils import parse_json_response
from app.generation.pollinations_image import generate_unique_image
from app.generation.text_combine import combine_source_text
from app.models.chat import Chat
from app.models.material_source import MaterialSource

SYSTEM_PROMPT = """You are a comic writer explaining study material to a curious reader. Given study material \
(possibly from multiple sources), produce a JSON object with:
- "panels": a list of 4-6 comic panels that walk through the material as a fun, simple comic strip. Each panel \
is an object with:
  - "scene_description": a CONCRETE, LITERAL visual description of the specific objects/process/diagram this \
panel is illustrating — name the actual things from the material (e.g. "magma chamber", "chloroplast", "a \
beehive"), not a generic decorative scene. State the art style explicitly: "flat 2D cartoon illustration, like \
a children's educational picture book, with simple bold outlines and flat colors". Include what the 1-2 \
recurring characters are doing/pointing at. Do NOT mention any text, words, letters, or speech bubbles in this \
description — describe only the visual scene.
  - "dialogue": EXACTLY 4 speech-bubble lines (this is a hard requirement, not a suggestion — never 1 or 2) that \
carry the actual explanation for this panel, alternating between the two characters. This is where the teaching \
content goes: each line should add a new piece of information, not just banter. Each is an object with "speaker" \
(a short character name or label) and "text" (one short sentence, under 16 words). Example shape for one panel: \
[{"speaker":"Rocky","text":"..."},{"speaker":"Dr. Gneiss","text":"..."},{"speaker":"Rocky","text":"..."},\
{"speaker":"Dr. Gneiss","text":"..."}]
  - "caption": an optional short narration caption for the panel, or null if not needed

Keep a consistent cast of 1-2 simple, fun recurring characters across all panels who explain the concept to each \
other, so the strip reads as one continuous story. The dialogue should teach the material step by step — by the \
last panel, the full concept should have been explained through the speech bubbles.

Respond with ONLY the JSON object, no markdown fences, no commentary."""

IMAGE_PROMPT_PREFIX = (
    "Flat 2D cartoon illustration in the style of a children's educational picture book, simple bold outlines "
    "and flat colors like a comic strip. Single scene only (not a grid or collage of multiple images), clearly "
    "depicting the specific subject described below and nothing else, no text, no letters, no speech bubbles, "
    "no writing anywhere in the image: "
)

IMAGE_SIZE = 768


class ComicGenerator(GeneratorInterface):
    mode = "comic"
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
        panels = script.get("panels") or []
        if not panels:
            raise ValueError("No comic panels were generated.")

        settings = get_settings()
        comic_id = str(uuid.uuid4())
        panels_dir = Path(settings.generated_dir) / "comics" / comic_id
        panels_dir.mkdir(parents=True, exist_ok=True)

        total = len(panels)
        image_error: str | None = None
        seen_image_hashes: set[str] = set()
        for i, panel in enumerate(panels):
            scene = (panel.get("scene_description") or "").strip()
            panel["image_url"] = None
            if not scene:
                if on_progress:
                    on_progress(i + 1, total)
                continue
            try:
                dest = panels_dir / f"panel_{i}.jpg"
                generate_unique_image(f"{IMAGE_PROMPT_PREFIX}{scene}", dest, seen_image_hashes, size=IMAGE_SIZE)
                panel["image_url"] = f"/media/comics/{comic_id}/panel_{i}.jpg"
            except Exception as exc:
                # One failed panel shouldn't sink the whole comic — the frontend shows a
                # placeholder for panels with image_url = None. Keep the first error so the UI
                # can explain *why* if every panel came back blank.
                image_error = image_error or str(exc)
            if on_progress:
                on_progress(i + 1, total)

        result: dict = {"panels": panels}
        if image_error and all(p.get("image_url") is None for p in panels):
            result["image_error"] = image_error
        return result
