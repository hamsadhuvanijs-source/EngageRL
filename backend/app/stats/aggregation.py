from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chat import Chat
from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.material_source import MaterialSource
from app.models.q_state import QState
from app.models.telemetry_event import TelemetryEvent
from app.models.user import User
from app.rl import bandit
from app.rl.actions import IMPLEMENTED_MODES
from app.rl.policy import active_policy, completed_session_count
from app.schemas.chat import ChatOut
from app.schemas.stats import EngagementPoint, ModePreference, RLPolicySummary, StatsOut

RECENT_CHATS_LIMIT = 5


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _q_value_averages(db: Session, user_id: str) -> dict[str, tuple[float, int]]:
    """Per-action (weighted_avg_q_value, total_visit_count) across every state the user has
    visited that action in — update_count-weighted so a (state, action) pair updated many times
    counts for more than one updated only once."""
    rows = db.query(QState).filter_by(user_id=user_id).all()
    totals: dict[str, tuple[float, int]] = {}
    for row in rows:
        weighted_sum, count = totals.get(row.action, (0.0, 0))
        totals[row.action] = (weighted_sum + row.q_value * row.update_count, count + row.update_count)
    return {action: (weighted_sum / count, count) for action, (weighted_sum, count) in totals.items() if count > 0}


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
            LearningSession.completed_at.isnot(None),
        )
        .order_by(LearningSession.completed_at)
        .all()
    )
    engagement_trend = [
        EngagementPoint(completed_at=s.completed_at, engagement_score=s.engagement_score) for s in trend_rows
    ]

    q_averages = _q_value_averages(db, user.id)

    mode_preference: dict[str, ModePreference] = {}
    for mode in IMPLEMENTED_MODES:
        state = bandit.get_or_create_state(db, user.id, mode)
        alpha = float(state.params_json.get("alpha", 1.0))
        beta = float(state.params_json.get("beta", 1.0))
        thompson_mean = alpha / (alpha + beta)

        q_value_avg, visit_count = q_averages.get(mode, (None, 0))
        preference = _clamp01(q_value_avg) if q_value_avg is not None else thompson_mean

        mode_preference[mode] = ModePreference(
            alpha=alpha,
            beta=beta,
            thompson_mean=thompson_mean,
            q_value_avg=q_value_avg,
            visit_count=visit_count,
            preference=preference,
        )

    recent_chats = (
        db.query(Chat).filter(Chat.user_id == user.id).order_by(Chat.updated_at.desc()).limit(RECENT_CHATS_LIMIT).all()
    )

    settings = get_settings()
    rl_policy = RLPolicySummary(
        active_policy=active_policy(db, user.id),
        completed_sessions=completed_session_count(db, user.id),
        cold_start_threshold=settings.rl_cold_start_session_threshold,
    )

    return StatsOut(
        chat_count=chat_count,
        source_count=source_count,
        session_count=session_count,
        total_active_seconds=float(total_active_seconds),
        engagement_trend=engagement_trend,
        mode_preference=mode_preference,
        recent_chats=[ChatOut.model_validate(c) for c in recent_chats],
        rl_policy=rl_policy,
    )
