from app.generation.base import TextGenerator

SYSTEM_PROMPT_TEMPLATE = """You are a study assistant. Given study material (possibly from multiple sources), produce a \
JSON object with:
- "cards": a list of EXACTLY {count} flashcards for quick recall practice, at a {difficulty} difficulty level — \
{difficulty_hint}. Each is an object with "question" (a short prompt, term, or question) and "answer" (a short, \
direct answer — one sentence or a few words, not a paragraph)

Respond with ONLY the JSON object, no markdown fences, no commentary."""

DIFFICULTY_HINTS = {
    "easy": "simple, direct terms and definitions stated plainly in the material",
    "medium": "requires connecting a term to its role or context, not just a bare definition",
    "hard": "subtle distinctions, edge cases, or applying a concept rather than just naming it",
}
VALID_COUNTS = {5, 10, 20}
DEFAULT_DIFFICULTY = "medium"
DEFAULT_COUNT = 10


class FlashcardsGenerator(TextGenerator):
    mode = "flashcards"

    def build_system_prompt(self, options: dict | None) -> str:
        options = options or {}
        difficulty = options.get("difficulty") if options.get("difficulty") in DIFFICULTY_HINTS else DEFAULT_DIFFICULTY
        count = options.get("num_questions") if options.get("num_questions") in VALID_COUNTS else DEFAULT_COUNT
        return SYSTEM_PROMPT_TEMPLATE.format(count=count, difficulty=difficulty, difficulty_hint=DIFFICULTY_HINTS[difficulty])
