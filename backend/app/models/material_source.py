import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SOURCE_TYPES = ("pdf", "txt", "youtube", "website", "pasted_text")
SOURCE_STATUSES = ("pending", "extracted", "failed")


class MaterialSource(Base):
    __tablename__ = "material_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16))
    original_ref: Mapped[str] = mapped_column(String(1024))
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
