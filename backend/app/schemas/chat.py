from datetime import datetime

from pydantic import BaseModel

from app.schemas.generated_content import GeneratedContentOut
from app.schemas.material_source import MaterialSourceOut


class ChatOut(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatDetailOut(BaseModel):
    chat: ChatOut
    sources: list[MaterialSourceOut]
    generations: list[GeneratedContentOut]
