import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BanditState(Base):
    __tablename__ = "bandit_state"
    __table_args__ = (UniqueConstraint("user_id", "mode", name="uq_bandit_state_user_mode"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(32))
    algo: Mapped[str] = mapped_column(String(32), default="thompson_beta")
    params_json: Mapped[dict] = mapped_column(JSON, default=lambda: {"alpha": 1.0, "beta": 1.0})
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
