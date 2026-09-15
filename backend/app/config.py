from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    # Tried in order when an earlier key hits its quota (e.g. the free-tier daily request cap).
    # That cap is enforced per Google Cloud *project*, so an extra key only buys real headroom
    # when it comes from a separate project/account. GEMINI_API_KEYS is a comma-separated list
    # for adding a third key and beyond without a new setting each time.
    gemini_api_key_backup: str = ""
    gemini_api_keys: str = ""
    database_url: str = "sqlite:///./app.db"
    upload_dir: str = "./uploads"
    generated_dir: str = "./generated"
    cors_origins: str = "http://localhost:3000"

    # Bearer-token lifetime. None = tokens never expire (fine for a local single-machine
    # deployment); set e.g. 30 to force re-login after 30 days.
    auth_token_ttl_days: int | None = None

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
    # Confidence-shrinkage pseudo-count (see qlearning.blended_q_values): how many observations
    # of a (state, action) pair it takes to weigh the state-specific Q-value as much as the
    # much-better-sampled cold-start bandit's per-mode prior. Higher = trust the sparse per-state
    # table less / lean on the pooled per-mode prior longer before it takes over.
    rl_shrinkage_pseudo_count: float = 3.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def gemini_api_key_list(self) -> list[str]:
        """Every configured Gemini key in fallback order, de-duplicated: primary, then backup,
        then any listed in GEMINI_API_KEYS."""
        raw = [self.gemini_api_key, self.gemini_api_key_backup, *self.gemini_api_keys.split(",")]
        keys: list[str] = []
        for key in (k.strip() for k in raw):
            if key and key not in keys:
                keys.append(key)
        return keys


@lru_cache
def get_settings() -> Settings:
    return Settings()
