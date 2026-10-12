from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user, require_owned_chat
from app.ingestion.chunking import chunk_text
from app.ingestion.extractors import extract_text, file_type_for
from app.ingestion.website import extract_website
from app.ingestion.youtube import extract_youtube
from app.models.chat import Chat
from app.models.material_source import MaterialSource
from app.models.user import User
from app.schemas.material_source import LinkSourceIn, MaterialSourceOut, TextSourceIn

router = APIRouter(tags=["sources"])

TEXT_LABEL_LENGTH = 60


@router.post("/chats/{chat_id}/sources/file", response_model=MaterialSourceOut)
async def add_file_source(
    chat_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialSourceOut:
    chat = require_owned_chat(db, chat_id, user)

    file_type = file_type_for(file.filename or "")
    if file_type is None:
        raise HTTPException(status_code=400, detail="Unsupported file type. Use .pdf or .txt")

    settings = get_settings()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    source = MaterialSource(chat_id=chat.id, source_type=file_type, original_ref=file.filename, status="pending")
    db.add(source)
    db.commit()
    db.refresh(source)

    dest_path = upload_dir / f"{source.id}_{file.filename}"
    contents = await file.read()
    dest_path.write_bytes(contents)

    try:
        raw_text = extract_text(dest_path, file_type)
        _finalize_source(source, raw_text)
    except Exception:
        source.status = "failed"

    _touch_chat_and_title(db, chat, source, fallback_title=Path(file.filename).stem)
    db.commit()
    db.refresh(source)
    return _source_to_out(source)


@router.post("/chats/{chat_id}/sources/link", response_model=MaterialSourceOut)
def add_link_source(
    chat_id: str,
    body: LinkSourceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialSourceOut:
    chat = require_owned_chat(db, chat_id, user)

    if body.source_type not in ("youtube", "website"):
        raise HTTPException(status_code=400, detail="source_type must be 'youtube' or 'website'")

    source = MaterialSource(chat_id=chat.id, source_type=body.source_type, original_ref=body.url, status="pending")
    db.add(source)
    db.commit()
    db.refresh(source)

    try:
        extractor = extract_youtube if body.source_type == "youtube" else extract_website
        raw_text, label = extractor(body.url)
        _finalize_source(source, raw_text)
        source.original_ref = label
    except Exception as exc:
        source.status = "failed"
        _touch_chat_and_title(db, chat, source, fallback_title=body.url)
        db.commit()
        raise HTTPException(status_code=422, detail=f"Could not extract that link: {exc}") from exc

    _touch_chat_and_title(db, chat, source, fallback_title=source.original_ref)
    db.commit()
    db.refresh(source)
    return _source_to_out(source)


@router.post("/chats/{chat_id}/sources/text", response_model=MaterialSourceOut)
def add_text_source(
    chat_id: str,
    body: TextSourceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaterialSourceOut:
    chat = require_owned_chat(db, chat_id, user)

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    label = body.text.strip()[:TEXT_LABEL_LENGTH]
    source = MaterialSource(chat_id=chat.id, source_type="pasted_text", original_ref=label, status="pending")
    db.add(source)
    db.commit()
    db.refresh(source)

    _finalize_source(source, body.text)
    _touch_chat_and_title(db, chat, source, fallback_title=label)
    db.commit()
    db.refresh(source)
    return _source_to_out(source)


@router.delete("/chats/{chat_id}/sources/{source_id}", status_code=204)
def delete_source(
    chat_id: str,
    source_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    chat = require_owned_chat(db, chat_id, user)
    source = db.get(MaterialSource, source_id)
    if source is None or source.chat_id != chat.id:
        raise HTTPException(status_code=404, detail="Source not found")

    if source.source_type in ("pdf", "txt"):
        settings = get_settings()
        file_path = Path(settings.upload_dir) / f"{source.id}_{source.original_ref}"
        file_path.unlink(missing_ok=True)

    db.delete(source)
    chat.updated_at = datetime.now(timezone.utc)
    db.commit()


def _finalize_source(source: MaterialSource, raw_text: str) -> None:
    source.raw_text = raw_text
    source.chunks = chunk_text(raw_text)
    source.char_count = len(raw_text)
    source.status = "extracted"


def _touch_chat_and_title(db: Session, chat: Chat, source: MaterialSource, fallback_title: str) -> None:
    if chat.title is None:
        chat.title = fallback_title[:256]
    chat.updated_at = datetime.now(timezone.utc)
    db.add(chat)


def _source_to_out(source: MaterialSource) -> MaterialSourceOut:
    preview = (source.raw_text or "")[:300]
    return MaterialSourceOut(
        id=source.id,
        chat_id=source.chat_id,
        source_type=source.source_type,
        original_ref=source.original_ref,
        char_count=source.char_count,
        status=source.status,
        created_at=source.created_at,
        text_preview=preview,
    )
