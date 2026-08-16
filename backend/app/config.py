from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    # Used automatically when the primary key hits its quota (e.g. free-tier daily limit).
    gemini_api_key_backup: str = ""
    database_url: str = "sqlite:///./app.db"
    upload_dir: str = "./uploads"
    generated_dir: str = "./generated"
    cors_origins: str = "http://localhost:3000"

    # A rolling alias Google keeps pointed at their current recommended flash model — avoids
    # hard-pinning a specific version that can later get deprecated for new API keys/projects.
    gemini_model: str = "gemini-flash-latest"

    # Local LLM (Ollama) for the tutor chat panel — no API key, runs on the user's machine.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
