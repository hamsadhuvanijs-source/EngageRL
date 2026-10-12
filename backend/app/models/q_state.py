import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class QState(Base):
    """One row per (user, discretized learner state, action) triple that has ever been visited —
    the tabular Q-table for the Q-learning policy. Unvisited triples simply have no row, which
    `app/rl/qlearning.py` treats as Q=0.0 (the standard zero-initialization for unseen
    state-action pairs), so the table only grows with real experience instead of needing to be
    pre-populated for the entire (large but sparsely-visited) state space.

    Persisted in the same database as everything else so learning survives process restarts —
    there is no in-memory-only Q-table anywhere in this system."""

    __tablename__ = "q_state"
    __table_args__ = (UniqueConstraint("user_id", "state_key", "action", name="uq_q_state_user_state_action"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    # Deterministic, human-readable encoding of the discretized learner state — see
    # app/rl/state.py::compute_state. Indexed (with user_id) since every action-selection and
    # every Q-update looks rows up by (user_id, state_key).
    state_key: Mapped[str] = mapped_column(String(256), index=True)
    action: Mapped[str] = mapped_column(String(32))
    q_value: Mapped[float] = mapped_column(Float, default=0.0)
    # How many times this exact (state, action) pair has been updated — not used in the Q-value
    # math, but useful for debugging/demonstrating which parts of the table are well-explored
    # versus a single noisy sample.
    update_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
