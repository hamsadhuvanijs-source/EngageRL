from pydantic import BaseModel


class SuggestModeOut(BaseModel):
    mode: str
    confidence: float
    all_scores: dict[str, float]


class PolicyStateOut(BaseModel):
    user_id: str
    modes: dict[str, dict]
