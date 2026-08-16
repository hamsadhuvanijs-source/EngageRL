from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.chat import Chat
from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.material_source import MaterialSource
from app.models.telemetry_event import TelemetryEvent
from app.models.user import User
from app.rl import bandit
from app.rl.bandit import ALL_MODES
from app.schemas.chat import ChatOut
from app.schemas.stats import EngagementPoint, ModePreference, StatsOut

RECENT_CHATS_LIMIT = 5


def compute_stats(db: Session, user: User) -> StatsOut:
    chat_count = db.query(func.count(Chat.id)).filter(Chat.user_id == user.id).scalar() or 0

    source_count = (
        db.query(func.count(MaterialSource.id))
        .join(Chat, MaterialSource.chat_id == Chat.id)
        .filter(Chat.user_id == user.id)
        .scalar()
        or 0
    )

    session_count = db.query(func.count(LearningSession.id)).filter(LearningSession.user_id == user.id).scalar() or 0

    dwell_events = (
        db.query(TelemetryEvent)
        .join(LearningSession, TelemetryEvent.session_id == LearningSession.id)
        .filter(LearningSession.user_id == user.id, TelemetryEvent.event_type == "dwell")
        .all()
    )
    total_active_seconds = sum(float((e.payload or {}).get("seconds", 0)) for e in dwell_events)

    trend_rows = (
        db.query(LearningSession)
        .filter(
            LearningSession.user_id == user.id,
            LearningSession.status == "completed",
            LearningSession.engagement_score.isnot(None),
        )
        .order_by(LearningSession.completed_at)
        .all()
    )
    engagement_trend = [
        EngagementPoint(completed_at=s.completed_at, engagement_score=s.engagement_score) for s in trend_rows
    ]

    mode_preference: dict[str, ModePreference] = {}
    for mode in ALL_MODES:
        state = bandit.get_or_create_state(db, user.id, mode)
        alpha = float(state.params_json.get("alpha", 1.0))
        beta = float(state.params_json.get("beta", 1.0))
        mode_preference[mode] = ModePreference(alpha=alpha, beta=beta, mean=alpha / (alpha + beta))

    recent_chats = (
        db.query(Chat).filter(Chat.user_id == user.id).order_by(Chat.updated_at.desc()).limit(RECENT_CHATS_LIMIT).all()
    )

    return StatsOut(
        chat_count=chat_count,
        source_count=source_count,
        session_count=session_count,
        total_active_seconds=float(total_active_seconds),
        engagement_trend=engagement_trend,
        mode_preference=mode_preference,
        recent_chats=[ChatOut.model_validate(c) for c in recent_chats],
    )
