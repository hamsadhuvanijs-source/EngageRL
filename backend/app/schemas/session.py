from datetime import datetime

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    generated_content_id: str


class SessionOut(BaseModel):
    id: str
    generated_content_id: str
    started_at: datetime
    completed_at: datetime | None
    engagement_score: float | None
    status: str

    model_config = {"from_attributes": True}


class TelemetryEventIn(BaseModel):
    event_type: str
    payload: dict = {}
    client_ts: datetime


class TelemetryBatchIn(BaseModel):
    events: list[TelemetryEventIn]


class SessionCompleteResponse(BaseModel):
    session: SessionOut
    engagement_score: float
    bandit_params: dict


class SessionDetailOut(BaseModel):
    session: SessionOut
    chat_id: str
    mode: str
    content_json: dict | None
    expected_seconds: float
    overage_threshold_seconds: float


class StillEngagedIn(BaseModel):
    still_engaged: bool


class StillEngagedOut(BaseModel):
    expected_seconds: float
    overage_threshold_seconds: float
    reading_pace_multiplier: float
