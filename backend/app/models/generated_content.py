import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MODES = ("summary", "quiz", "flashcards", "qa", "flowchart", "podcast", "comic", "video")
CONTENT_STATUSES = ("pending", "ready", "failed")


class GeneratedContent(Base):
    __tablename__ = "generated_content"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), index=True)
    mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # User-chosen generation options (difficulty, question count, summary length, etc.) — mode
    # specific, interpreted by each generator. Null/missing keys fall back to defaults.
    options_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Only populated for generators that run in the background and report progress
    # (comic and video — per-panel/per-scene image (+ narration) generation is too slow to do inline).
    progress_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
