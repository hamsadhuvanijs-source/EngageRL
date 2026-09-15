from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_owned_chat, require_owned_session
from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.user import User
from app.rl.hooks import on_session_end
from app.rl.policy import snapshot_decision
from app.schemas.session import (
    SessionCompleteResponse,
    SessionCreateRequest,
    SessionDetailOut,
    SessionOut,
    StillEngagedIn,
    StillEngagedOut,
)
from app.telemetry.scoring import bump_reading_pace, expected_seconds_for_session

router = APIRouter(tags=["sessions"])


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
def get_session(
    session_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> SessionDetailOut:
    session = require_owned_session(db, session_id, user)

    content = db.get(GeneratedContent, session.generated_content_id)
    expected_seconds, overage_threshold_seconds = expected_seconds_for_session(db, session)
    return SessionDetailOut(
        session=session,
        chat_id=content.chat_id,
        mode=content.mode,
        content_json=content.content_json,
        expected_seconds=expected_seconds,
        overage_threshold_seconds=overage_threshold_seconds,
    )


@router.post("/sessions/{session_id}/still-engaged", response_model=StillEngagedOut)
def still_engaged(
    session_id: str,
    body: StillEngagedIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StillEngagedOut:
    """Called from the 'still with it?' check-in popup. Confirming engagement bumps the user's
    personal pace multiplier so future sessions get a longer grace window before flagging again;
    saying they're not interested is just acknowledged here — the frontend follows up with a
    suggest-mode call to offer an alternative, and the real signal still comes from how the rest
    of this session's telemetry actually plays out, not a self-report."""
    session = require_owned_session(db, session_id, user)

    if body.still_engaged:
        bump_reading_pace(user)
        db.commit()
        db.refresh(user)

    expected_seconds, overage_threshold_seconds = expected_seconds_for_session(db, session)
    return StillEngagedOut(
        expected_seconds=expected_seconds,
        overage_threshold_seconds=overage_threshold_seconds,
        reading_pace_multiplier=user.reading_pace_multiplier,
    )


@router.post("/sessions", response_model=SessionOut)
def create_session(
    body: SessionCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LearningSession:
    content = db.get(GeneratedContent, body.generated_content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Generated content not found")
    if content.status != "ready":
        raise HTTPException(status_code=400, detail="Generated content is not ready yet")

    chat = require_owned_chat(db, content.chat_id, user)

    session = LearningSession(user_id=user.id, generated_content_id=content.id, status="active")
    if chat is not None:
        # Snapshot the MDP decision context (state + action) now, before the learner has
        # interacted with this content at all — this is the (state, action) half of the RL
        # transition; app/rl/hooks.py::on_session_end fills in (reward, next_state, done) once
        # the session completes. See app/rl/policy.py::snapshot_decision.
        for key, value in snapshot_decision(db, user, chat, content.mode).items():
            setattr(session, key, value)

    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.patch("/sessions/{session_id}/complete", response_model=SessionCompleteResponse)
def complete_session(
    session_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> SessionCompleteResponse:
    session = require_owned_session(db, session_id, user)

    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)

    score, bandit_params = on_session_end(db, session)
    db.refresh(session)

    return SessionCompleteResponse(session=session, engagement_score=score, bandit_params=bandit_params)
