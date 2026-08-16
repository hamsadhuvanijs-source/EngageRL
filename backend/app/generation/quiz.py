from app.generation.base import TextGenerator

SYSTEM_PROMPT_TEMPLATE = """You are a study assistant. Given study material (possibly from multiple sources), produce a \
JSON object with:
- "quiz": a list of EXACTLY {count} multiple-choice questions at a {difficulty} difficulty level — {difficulty_hint}. \
Each is an object with "question", "options" (list of 4 strings), "correct_index" (0-based int), and "explanation" \
(why the answer is correct)

Respond with ONLY the JSON object, no markdown fences, no commentary."""

DIFFICULTY_HINTS = {
    "easy": "straightforward recall of basic facts stated directly in the material",
    "medium": "requires understanding and connecting a couple of concepts from the material, not just recall",
    "hard": "requires deeper reasoning, applying concepts to new situations, or distinguishing subtle differences",
}
VALID_COUNTS = {5, 10, 20}
DEFAULT_DIFFICULTY = "medium"
DEFAULT_COUNT = 10


class QuizGenerator(TextGenerator):
    mode = "quiz"

    def build_system_prompt(self, options: dict | None) -> str:
        options = options or {}
        difficulty = options.get("difficulty") if options.get("difficulty") in DIFFICULTY_HINTS else DEFAULT_DIFFICULTY
        count = options.get("num_questions") if options.get("num_questions") in VALID_COUNTS else DEFAULT_COUNT
        return SYSTEM_PROMPT_TEMPLATE.format(count=count, difficulty=difficulty, difficulty_hint=DIFFICULTY_HINTS[difficulty])
