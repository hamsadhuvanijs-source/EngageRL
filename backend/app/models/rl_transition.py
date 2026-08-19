import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RL_POLICIES = ("cold_start_thompson", "q_learning")


class RLTransition(Base):
    """One recorded (state, action, reward, next_state, done) MDP transition — the actual audit
    trail of what the agent observed and learned from, one row per completed learning session.
    Kept independently of `QState` (which only holds the *current* aggregated Q-values) so the
    full learning trajectory — what happened, in what order, under which policy — can be
    inspected and debugged rather than only seeing the latest converged numbers."""

    __tablename__ = "rl_transitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    # The chat is the "learning topic / study journey" — the episode this transition belongs to.
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("learning_sessions.id"), unique=True)

    state_key: Mapped[str] = mapped_column(String(256))
    # Full, readable feature breakdown behind state_key (e.g. {"engagement": "high", ...}) —
    # redundant with state_key but much easier to read in a debugger/DB browser.
    state_json: Mapped[dict] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(32))
    reward: Mapped[float] = mapped_column(Float)
    next_state_key: Mapped[str] = mapped_column(String(256))
    next_state_json: Mapped[dict] = mapped_column(JSON)
    # Terminal-state flag for this episode (see app/rl/reward.py::is_topic_mastered) — when True,
    # the Q-update target is the reward alone with no bootstrapped next-state value.
    done: Mapped[bool] = mapped_column(Boolean, default=False)

    # Which policy regime was active for this user when the action was taken — NOT necessarily
    # proof the policy's own greedy pick was followed (the learner is always free to pick any
    # format manually; Q-learning is off-policy and learns from whatever action actually
    # happened either way). See app/rl/policy.py.
    policy: Mapped[str] = mapped_column(String(32))
    epsilon: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
