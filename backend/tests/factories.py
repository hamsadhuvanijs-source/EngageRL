"""Small helpers for building the object graph RL tests need (user -> chat -> generated
content -> session -> telemetry events) without each test hand-rolling it."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.chat import Chat
from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.telemetry_event import TelemetryEvent
from app.models.user import User


def make_user(db: Session, **kwargs) -> User:
    user = User(**kwargs)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_chat(db: Session, user: User, title: str | None = "Test topic") -> Chat:
    chat = Chat(user_id=user.id, title=title)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


def make_content(
    db: Session, chat: Chat, mode: str = "quiz", content_json: dict | None = None, options_json: dict | None = None
) -> GeneratedContent:
    content = GeneratedContent(
        chat_id=chat.id,
        mode=mode,
        status="ready",
        content_json=content_json or {"quiz": [{"question": "q", "options": ["a", "b"], "correct_index": 0}]},
        options_json=options_json,
    )
    db.add(content)
    db.commit()
    db.refresh(content)
    return content


def make_session(
    db: Session,
    user: User,
    content: GeneratedContent,
    status: str = "completed",
    engagement_score: float | None = 0.8,
    **rl_fields,
) -> LearningSession:
    session = LearningSession(
        user_id=user.id,
        generated_content_id=content.id,
        status=status,
        engagement_score=engagement_score,
        completed_at=datetime.now(timezone.utc) if status == "completed" else None,
        **rl_fields,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def add_event(db: Session, session: LearningSession, event_type: str, payload: dict) -> TelemetryEvent:
    event = TelemetryEvent(
        session_id=session.id, event_type=event_type, payload=payload, client_ts=datetime.now(timezone.utc)
    )
    db.add(event)
    db.commit()
    return event
