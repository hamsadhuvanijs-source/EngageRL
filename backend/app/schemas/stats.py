from datetime import datetime

from pydantic import BaseModel

from app.schemas.chat import ChatOut


class EngagementPoint(BaseModel):
    completed_at: datetime
    engagement_score: float


class ModePreference(BaseModel):
    # Legacy cold-start Thompson posterior — no longer the main policy (see
    # app/rl/bandit.py), kept for continuity/back-compat display only.
    alpha: float
    beta: float
    thompson_mean: float
    # Q-learning signal: this action's Q-value averaged across every discretized state the user
    # has visited it in, weighted by how many times each (state, action) pair was updated. None
    # if Q-learning has never actually chosen/observed this action yet for this user.
    q_value_avg: float | None
    visit_count: int
    # Single 0-1 display value the dashboard bar chart renders: q_value_avg (clamped) once
    # there's Q-learning data for this action, otherwise the Thompson mean as a cold-start
    # fallback — see app/stats/aggregation.py::compute_stats.
    preference: float


class RLPolicySummary(BaseModel):
    active_policy: str
    completed_sessions: int
    cold_start_threshold: int


class StatsOut(BaseModel):
    chat_count: int
    source_count: int
    session_count: int
    total_active_seconds: float
    engagement_trend: list[EngagementPoint]
    mode_preference: dict[str, ModePreference]
    recent_chats: list[ChatOut]
    rl_policy: RLPolicySummary
