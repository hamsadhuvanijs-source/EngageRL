from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth.service import resolve_token
from app.db import get_db
from app.models.chat import Chat
from app.models.learning_session import LearningSession
from app.models.user import User


def bearer_token(authorization: str | None = Header(default=None)) -> str:
    """Pull the raw token out of an ``Authorization: Bearer <token>`` header, or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    token: str = Depends(bearer_token), db: Session = Depends(get_db)
) -> User:
    user = resolve_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def require_owned_chat(db: Session, chat_id: str, user: User) -> Chat:
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if chat.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your chat")
    return chat


def require_owned_session(db: Session, session_id: str, user: User) -> LearningSession:
    session = db.get(LearningSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your session")
    return session
