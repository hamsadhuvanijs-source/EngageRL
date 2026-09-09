import time
from functools import lru_cache

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import get_settings

QUOTA_EXHAUSTED_CODE = 429

# Transient failures worth retrying rather than failing the whole generation over: Gemini itself
# reporting overload (ServerError, e.g. 503 UNAVAILABLE — Google's own message says spikes are
# usually temporary), and transport-level failures that never even reach Gemini's servers
# (httpx.ConnectError covers DNS resolution blips — "[Errno 11001] getaddrinfo failed" on
# Windows — refused connections, etc; httpx.TimeoutException covers a hung request). The
# google-genai SDK has its own tenacity-based retry, but it's opt-in via HttpRetryOptions and
# unconfigured here, so by default it retries nothing — this wrapper is the only retry layer.
# 3 quick retries (~6s total) turned out not to be enough for real spikes, which can run tens of
# seconds — so this waits longer, capped per-attempt so it doesn't run away exponentially.
TRANSIENT_SERVER_RETRIES = 5
TRANSIENT_SERVER_BACKOFF_SECONDS = 3.0
TRANSIENT_SERVER_BACKOFF_CAP_SECONDS = 15.0

# For callers that already run in a background thread with their own progress UI (video, comic
# — see generation/router.py's supports_progress path) and so aren't blocking an HTTP request by
# waiting: worth riding out a much longer demand spike (~3-4 min across both keys) rather than
# failing a multi-minute generation over a transient window.
BACKGROUND_TRANSIENT_SERVER_RETRIES = 10


@lru_cache
def _client_for_key(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _get_clients() -> list[genai.Client]:
    keys = get_settings().gemini_api_key_list
    if not keys:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
    return [_client_for_key(k) for k in keys]


def complete_json(system: str, user: str, max_output_tokens: int = 4000, max_retries: int | None = None) -> str:
    """Single-turn completion, asking Gemini to return raw JSON text. Falls back to the next
    configured API key (see Settings.gemini_api_key_list) when one hits its quota (e.g. the
    free-tier daily request cap).

    `max_retries` overrides TRANSIENT_SERVER_RETRIES per call site — callers that run in a
    blocking HTTP request (summary/quiz/flashcards/qa) shouldn't make the user's browser hang
    for minutes, so they keep the default. Callers that already run in a background thread with
    their own progress UI (video/comic — see generation/router.py's `supports_progress` path)
    aren't blocking anything by waiting longer, so they can afford to ride out a longer Gemini
    demand spike instead of failing the whole generation over it."""
    settings = get_settings()
    clients = _get_clients()
    retries = max_retries if max_retries is not None else TRANSIENT_SERVER_RETRIES

    last_exc: Exception | None = None
    for client in clients:
        for attempt in range(retries):
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
            except (genai_errors.ServerError, httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < retries - 1:
                    delay = min(TRANSIENT_SERVER_BACKOFF_SECONDS * (2**attempt), TRANSIENT_SERVER_BACKOFF_CAP_SECONDS)
                    time.sleep(delay)
                    continue
                break

    raise last_exc or RuntimeError("All Gemini API keys are exhausted.")
