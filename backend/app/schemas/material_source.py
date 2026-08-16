from datetime import datetime

from pydantic import BaseModel


class MaterialSourceOut(BaseModel):
    id: str
    chat_id: str
    source_type: str
    original_ref: str
    char_count: int
    status: str
    created_at: datetime
    text_preview: str | None = None

    model_config = {"from_attributes": True}


class LinkSourceIn(BaseModel):
    source_type: str  # "youtube" | "website"
    url: str


class TextSourceIn(BaseModel):
    text: str
