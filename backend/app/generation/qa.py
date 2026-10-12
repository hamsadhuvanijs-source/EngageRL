from app.generation.base import TextGenerator

SYSTEM_PROMPT_TEMPLATE = """You are a study assistant. Given study material (possibly from multiple sources), produce a \
JSON object with:
- "items": a list of EXACTLY {count} question/answer pairs that work as a readable study guide, each an object with \
"question" and "answer" ({answer_style_instruction})

Respond with ONLY the JSON object, no markdown fences, no commentary."""

ANSWER_STYLE_INSTRUCTIONS = {
    "short": "a short, direct answer — one sentence, no more",
    "long": "a thorough, descriptive answer — several sentences with explanation and context, not just a one-liner",
}
VALID_COUNTS = {5, 10, 20}
DEFAULT_ANSWER_STYLE = "long"
DEFAULT_COUNT = 10


class QAGenerator(TextGenerator):
    mode = "qa"

    def build_system_prompt(self, options: dict | None) -> str:
        options = options or {}
        answer_style = (
            options.get("answer_style") if options.get("answer_style") in ANSWER_STYLE_INSTRUCTIONS else DEFAULT_ANSWER_STYLE
        )
        count = options.get("num_questions") if options.get("num_questions") in VALID_COUNTS else DEFAULT_COUNT
        return SYSTEM_PROMPT_TEMPLATE.format(count=count, answer_style_instruction=ANSWER_STYLE_INSTRUCTIONS[answer_style])
