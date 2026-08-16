from datetime import datetime

from pydantic import BaseModel


class TutorMessageIn(BaseModel):
    content: str


class TutorMessageOut(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TutorReplyOut(BaseModel):
    user_message: TutorMessageOut
    assistant_message: TutorMessageOut
