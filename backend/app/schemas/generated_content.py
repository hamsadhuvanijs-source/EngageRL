from datetime import datetime

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    mode: str
    options: dict | None = None


class GeneratedContentOut(BaseModel):
    id: str
    chat_id: str
    mode: str
    status: str
    content_json: dict | None
    options_json: dict | None = None
    model_used: str | None
    progress_current: int | None = None
    progress_total: int | None = None
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
