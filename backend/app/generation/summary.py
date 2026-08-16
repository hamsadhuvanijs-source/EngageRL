from app.generation.base import TextGenerator

SYSTEM_PROMPT_TEMPLATE = """You are a study assistant. Given study material (possibly from multiple sources), produce a \
JSON object with:
- "summary": {length_instruction}

Respond with ONLY the JSON object, no markdown fences, no commentary."""

LENGTH_INSTRUCTIONS = {
    "concise": (
        "a short, tightly-written summary (2-3 short paragraphs) covering only the most essential points — "
        "no filler, no minor details"
    ),
    "detailed": (
        "a thorough, detailed summary (6-10 paragraphs or well-organized bullet groups) covering the material "
        "in depth, including secondary details and examples"
    ),
}
DEFAULT_LENGTH = "concise"


class SummaryGenerator(TextGenerator):
    mode = "summary"

    def build_system_prompt(self, options: dict | None) -> str:
        options = options or {}
        length = options.get("length") if options.get("length") in LENGTH_INSTRUCTIONS else DEFAULT_LENGTH
        return SYSTEM_PROMPT_TEMPLATE.format(length_instruction=LENGTH_INSTRUCTIONS[length])
