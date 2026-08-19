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

    # --- Tabular Q-learning (app/rl/qlearning.py) ---
    # Learning rate: how much each new transition moves Q(s,a) toward the freshly observed
    # target. Kept low-ish since rewards are noisy (real human behavior, small per-user sample
    # sizes) — a high alpha would make Q-values swing wildly on one unusual session.
    rl_alpha: float = 0.15
    # Discount factor for future reward in the Bellman target. <1 so an episode that never hits
    # a terminal/mastery state still has a bounded, converging Q-value instead of accumulating
    # forever.
    rl_gamma: float = 0.9
    # Epsilon-greedy exploration, decayed per Q-learning-phase transition (not cold-start
    # transitions — those already explore via Thompson sampling). Starts moderate rather than at
    # 1.0 because cold start already handled the "we know nothing" phase.
    rl_epsilon_start: float = 0.3
    rl_epsilon_min: float = 0.05
    rl_epsilon_decay: float = 0.95
    # How many completed sessions a user needs before the main policy switches from cold-start
    # Thompson sampling to Q-learning action selection (Q-learning still learns from cold-start
    # transitions from session 1 — this only gates which policy does the *choosing*).
    rl_cold_start_session_threshold: int = 3

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
