from datetime import datetime

from pydantic import BaseModel


class SuggestModeOut(BaseModel):
    mode: str
    # 0-1 display-friendly confidence in `mode`. Under cold-start Thompson sampling this is the
    # Beta posterior mean (already 0-1). Under Q-learning it's the chosen action's Q-value
    # rescaled back onto the reward's [0, 1] scale (see app/rl/qlearning.py::q_to_reward_scale)
    # and clamped — a raw Q-value is a discounted sum of future rewards, not a probability, and
    # commonly exceeds 1 for any action that keeps getting picked with a decent reward.
    confidence: float
    policy: str  # "cold_start_thompson" | "q_learning" — see app/rl/policy.py
    epsilon: float | None = None
    state_key: str
    state: dict[str, str]
    # Per-action scores backing `confidence` — Thompson posterior means during cold start,
    # reward-scaled Q-values for the current state during Q-learning (see
    # app/rl/qlearning.py::q_to_reward_scale). Kept under one name across both regimes so the
    # frontend doesn't need to branch on which policy is active to render alternatives.
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
