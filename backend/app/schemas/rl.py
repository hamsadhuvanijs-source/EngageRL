from datetime import datetime

from pydantic import BaseModel


class SuggestModeOut(BaseModel):
    mode: str
    # 0-1 display-friendly confidence in `mode`. Under cold-start Thompson sampling this is the
    # Beta posterior mean (already 0-1). Under Q-learning it's the chosen action's Q-value,
    # clamped into [0, 1] for display — Q-values aren't a probability, but in practice stay in a
    # comparable range since rewards are bounded [0, 1] and episodes terminate at real mastery
    # events (see app/rl/reward.py::is_topic_mastered) rather than accumulating indefinitely.
    confidence: float
    policy: str  # "cold_start_thompson" | "q_learning" — see app/rl/policy.py
    epsilon: float | None = None
    state_key: str
    state: dict[str, str]
    # Per-action scores backing `confidence` — Thompson posterior means during cold start,
    # Q-values for the current state during Q-learning. Kept under one name across both regimes
    # so the frontend doesn't need to branch on which policy is active to render alternatives.
    action_scores: dict[str, float]


class QTableEntryOut(BaseModel):
    state_key: str
    state: dict[str, str]
    action: str
    q_value: float
    update_count: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class RLTransitionOut(BaseModel):
    id: str
    chat_id: str
    session_id: str
    state_key: str
    state: dict[str, str]
    action: str
    reward: float
    next_state_key: str
    next_state: dict[str, str]
    done: bool
    policy: str
    epsilon: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PolicyStateOut(BaseModel):
    user_id: str
    active_policy: str
    epsilon: float | None
    completed_sessions: int
    cold_start_threshold: int
    # Legacy cold-start bandit params, kept for continuity/back-compat — no longer the main
    # policy (see app/rl/bandit.py module docstring).
    bandit_params: dict[str, dict]
    q_table: list[QTableEntryOut]
    recent_transitions: list[RLTransitionOut]
