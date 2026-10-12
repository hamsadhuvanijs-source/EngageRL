import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuthToken(Base):
    """One row per issued bearer token. Only the SHA-256 hash of the token is stored, so the
    raw token exists exactly once (in the response to login/register) and can never be
    recovered from the database. Deleting the row revokes the token (logout)."""

    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Null means "never expires" (auth_token_ttl_days unset). Naive UTC, matching the rest of
    # the schema.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
