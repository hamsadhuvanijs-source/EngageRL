from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.chat import Chat
from app.rl import bandit
from app.rl.bandit import ALL_MODES
from app.schemas.rl import PolicyStateOut, SuggestModeOut

router = APIRouter(tags=["rl"])


@router.get("/chats/{chat_id}/suggest-mode", response_model=SuggestModeOut)
def suggest_mode(chat_id: str, db: Session = Depends(get_db)) -> SuggestModeOut:
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    user = get_current_user(db)
    mode, confidence, all_scores = bandit.suggest(db, user.id)
    return SuggestModeOut(mode=mode, confidence=confidence, all_scores=all_scores)


@router.get("/rl/policy-state", response_model=PolicyStateOut)
def policy_state(db: Session = Depends(get_db)) -> PolicyStateOut:
    user = get_current_user(db)
    modes = {}
    for mode in ALL_MODES:
        state = bandit.get_or_create_state(db, user.id, mode)
        modes[mode] = state.params_json
    return PolicyStateOut(user_id=user.id, modes=modes)
