from datetime import datetime

from pydantic import BaseModel

from app.schemas.chat import ChatOut


class EngagementPoint(BaseModel):
    completed_at: datetime
    engagement_score: float


class ModePreference(BaseModel):
    alpha: float
    beta: float
    mean: float


class StatsOut(BaseModel):
    chat_count: int
    source_count: int
    session_count: int
    total_active_seconds: float
    engagement_trend: list[EngagementPoint]
    mode_preference: dict[str, ModePreference]
    recent_chats: list[ChatOut]
