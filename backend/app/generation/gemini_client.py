import time
from functools import lru_cache

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import get_settings

QUOTA_EXHAUSTED_CODE = 429

# Transient upstream overload (e.g. 503 UNAVAILABLE, "high demand" — Google's own message
# says spikes are usually temporary) is worth retrying a few times before giving up or
# burning a fallback API key on something that isn't actually about that key. 3 quick retries
# (~6s total) turned out not to be enough for real spikes, which can run tens of seconds —
# so this waits longer, capped per-attempt so it doesn't run away exponentially.
TRANSIENT_SERVER_RETRIES = 5
TRANSIENT_SERVER_BACKOFF_SECONDS = 3.0
TRANSIENT_SERVER_BACKOFF_CAP_SECONDS = 15.0


@lru_cache
def _client_for_key(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _get_clients() -> list[genai.Client]:
    settings = get_settings()
    keys = [k for k in (settings.gemini_api_key, settings.gemini_api_key_backup) if k]
    if not keys:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
    return [_client_for_key(k) for k in keys]


def complete_json(system: str, user: str, max_output_tokens: int = 4000) -> str:
    """Single-turn completion, asking Gemini to return raw JSON text. Falls back to the backup
    API key if the primary one has hit its quota (e.g. the free-tier daily request cap)."""
    settings = get_settings()
    clients = _get_clients()

    last_exc: Exception | None = None
    for client in clients:
        for attempt in range(TRANSIENT_SERVER_RETRIES):
            try:
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=max_output_tokens,
                        response_mime_type="application/json",
                    ),
                )
                return response.text or ""
            except genai_errors.ClientError as exc:
                if exc.code == QUOTA_EXHAUSTED_CODE:
                    last_exc = exc
                    break
                raise
            except genai_errors.ServerError as exc:
                last_exc = exc
                if attempt < TRANSIENT_SERVER_RETRIES - 1:
                    delay = min(TRANSIENT_SERVER_BACKOFF_SECONDS * (2**attempt), TRANSIENT_SERVER_BACKOFF_CAP_SECONDS)
                    time.sleep(delay)
                    continue
                break

    raise last_exc or RuntimeError("All Gemini API keys are exhausted.")
