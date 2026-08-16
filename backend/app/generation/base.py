from abc import ABC, abstractmethod
from typing import Callable

from app.generation.gemini_client import complete_json
from app.generation.json_utils import parse_json_response
from app.generation.text_combine import combine_source_text
from app.models.chat import Chat
from app.models.material_source import MaterialSource

ProgressCallback = Callable[[int, int], None]


class GeneratorInterface(ABC):
    """Every learning mode implements this. Keeps flowchart/podcast/comic pluggable
    as siblings to the text-based modes without touching the dispatch/router code."""

    mode: str
    # Generators this slow run in a background thread with progress polling instead of
    # blocking the request — see generation/router.py. Everything else stays synchronous.
    supports_progress: bool = False

    @abstractmethod
    def generate(
        self,
        chat: Chat,
        sources: list[MaterialSource],
        options: dict | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        """Return a JSON-serializable payload to store as GeneratedContent.content_json.
        `options` is the user's mode-specific generation choices (difficulty, question count,
        summary length, etc.) — generators that don't take any just ignore it. `on_progress`
        is only ever called by generators with supports_progress=True."""
        raise NotImplementedError


class TextGenerator(GeneratorInterface):
    """Shared implementation for modes that are a single Gemini call over the chat's
    combined source text, asked to return a JSON object matching the system prompt."""

    system_prompt: str

    def build_system_prompt(self, options: dict | None) -> str:
        """Override to vary the prompt based on user-chosen options. Defaults to the static
        system_prompt for generators that don't take any options."""
        return self.system_prompt

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

        raw = complete_json(self.build_system_prompt(options), text)
        return parse_json_response(raw)
