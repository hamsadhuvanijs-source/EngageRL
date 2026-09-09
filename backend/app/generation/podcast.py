from app.generation.base import TextGenerator
from app.generation.gemini_client import BACKGROUND_TRANSIENT_SERVER_RETRIES

SYSTEM_PROMPT_TEMPLATE = """You are writing a two-host educational podcast episode that teaches study material \
through a natural, engaging conversation. Given study material (possibly from multiple sources), produce a JSON \
object with:
- "title": a short, catchy episode title
- "hosts": a list of EXACTLY 2 host objects — pick fun, distinct first names, not generic labels like "Host 1". \
Each object has "name" (the host's first name) and "gender" (either "female" or "male", matching the name you \
picked — this is used to select a matching text-to-speech voice, so it must actually match, e.g. "Maya" is \
"female", "Leo" is "male")
- "segments": {length_instruction} of back-and-forth dialogue between the two hosts, alternating naturally (not \
strictly one-for-one — a host can speak twice in a row if it's natural, e.g. asking a follow-up). Each segment is \
an object with "speaker" (must exactly match one of the two names in "hosts") and "text" (one or two natural \
spoken sentences — conversational, no markdown, no lists, written as if spoken out loud). Together the segments \
should teach the full material step by step: one host explains, the other asks clarifying questions, reacts, or \
adds a detail, the way real co-hosts riff off each other. Open with a quick, welcoming intro to the topic and \
close with a short wrap-up line.

Respond with ONLY the JSON object, no markdown fences, no commentary."""

LENGTH_INSTRUCTIONS = {
    "short": "6-8 segments",
    "long": "14-18 segments",
}
DEFAULT_LENGTH = "short"


class PodcastGenerator(TextGenerator):
    mode = "podcast"
    # The script call already runs ~90s+ synchronously (see the frontend's simulated progress
    # bar), so it's worth riding out a longer Gemini demand spike (503 UNAVAILABLE) rather than
    # failing after the default ~5-retry/~50s budget used by the fast text modes.
    max_retries = BACKGROUND_TRANSIENT_SERVER_RETRIES

    def build_system_prompt(self, options: dict | None) -> str:
        options = options or {}
        length = options.get("length") if options.get("length") in LENGTH_INSTRUCTIONS else DEFAULT_LENGTH
        return SYSTEM_PROMPT_TEMPLATE.format(length_instruction=LENGTH_INSTRUCTIONS[length])
