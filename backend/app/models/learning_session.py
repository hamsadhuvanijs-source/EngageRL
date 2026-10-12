import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SESSION_STATUSES = ("active", "completed", "abandoned")


class LearningSession(Base):
    __tablename__ = "learning_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    generated_content_id: Mapped[str] = mapped_column(String(36), ForeignKey("generated_content.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    engagement_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")

    # Snapshot of the MDP decision context, taken at session creation (before the learner has
    # interacted with this action at all) — see app/rl/policy.py::snapshot_decision. Nullable
    # because sessions created before this feature shipped have none; app/rl/state.py falls
    # back to recomputing from source data (GeneratedContent joins etc.) wherever it needs mode
    # history, so old rows don't break state computation.
    rl_state_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    rl_state_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rl_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rl_policy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rl_epsilon: Mapped[float | None] = mapped_column(Float, nullable=True)
