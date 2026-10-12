import httpx

from app.config import get_settings

CHAT_TIMEOUT_SECONDS = 120.0


class OllamaUnavailableError(Exception):
    """Raised when the local Ollama server can't be reached or the model isn't pulled."""


def chat(messages: list[dict[str, str]]) -> str:
    settings = get_settings()
    try:
        response = httpx.post(
            f"{settings.ollama_base_url}/api/chat",
            json={"model": settings.ollama_model, "messages": messages, "stream": False},
            timeout=CHAT_TIMEOUT_SECONDS,
        )
    except httpx.ConnectError as exc:
        raise OllamaUnavailableError(
            f"Can't reach Ollama at {settings.ollama_base_url}. Make sure Ollama is running "
            f"(`ollama serve`) and the '{settings.ollama_model}' model is pulled "
            f"(`ollama pull {settings.ollama_model}`)."
        ) from exc
    except httpx.HTTPError as exc:
        raise OllamaUnavailableError(f"Ollama request failed: {exc}") from exc

    if response.status_code == 404:
        raise OllamaUnavailableError(
            f"Model '{settings.ollama_model}' isn't pulled. Run `ollama pull {settings.ollama_model}`."
        )
    response.raise_for_status()
    return response.json()["message"]["content"]
