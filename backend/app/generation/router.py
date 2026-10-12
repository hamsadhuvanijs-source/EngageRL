import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.deps import get_current_user, require_owned_chat
from app.generation.base import GeneratorInterface
from app.generation.comic import ComicGenerator
from app.generation.flashcards import FlashcardsGenerator
from app.generation.flowchart import FlowchartGenerator
from app.generation.podcast import PodcastGenerator
from app.generation.qa import QAGenerator
from app.generation.quiz import QuizGenerator
from app.generation.summary import SummaryGenerator
from app.generation.video import VideoGenerator
from app.models.chat import Chat
from app.models.generated_content import GeneratedContent
from app.models.material_source import MaterialSource
from app.models.user import User
from app.schemas.generated_content import GenerateRequest, GeneratedContentOut

router = APIRouter(tags=["generation"])

_GENERATORS: dict[str, GeneratorInterface] = {
    "summary": SummaryGenerator(),
    "quiz": QuizGenerator(),
    "flashcards": FlashcardsGenerator(),
    "qa": QAGenerator(),
    "flowchart": FlowchartGenerator(),
    "podcast": PodcastGenerator(),
    "comic": ComicGenerator(),
    "video": VideoGenerator(),
}

_MODEL_USED_SUFFIX = {"comic": "+pollinations", "video": "+pollinations+edge-tts"}


@router.post("/chats/{chat_id}/generate", response_model=GeneratedContentOut)
def generate_content(
    chat_id: str,
    body: GenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeneratedContent:
    chat = require_owned_chat(db, chat_id, user)

    generator = _GENERATORS.get(body.mode)
    if generator is None:
        raise HTTPException(status_code=400, detail=f"Unknown mode: {body.mode}")

    content = GeneratedContent(chat_id=chat.id, mode=body.mode, status="pending", options_json=body.options)
    db.add(content)
    db.commit()
    db.refresh(content)

    if generator.supports_progress:
        # Slow, multi-step generators (comic, video — one Pollinations request per panel/scene,
        # sequential due to rate limits, plus TTS + video muxing for video) run in a background
        # thread instead of blocking this request for minutes. The frontend polls
        # GET /generated-content/{id} for progress.
        thread = threading.Thread(
            target=_run_in_background, args=(content.id, chat_id, body.mode, body.options), daemon=True
        )
        thread.start()
        return content

    sources = db.query(MaterialSource).filter(MaterialSource.chat_id == chat_id).all()
    try:
        payload = generator.generate(chat, sources, options=body.options)
    except NotImplementedError as exc:
        content.status = "failed"
        db.commit()
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        content.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"Generation failed: {exc}") from exc

    content.content_json = payload
    content.status = "ready"
    content.model_used = get_settings().gemini_model
    chat.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(content)
    return content


@router.get("/generated-content/{content_id}", response_model=GeneratedContentOut)
def get_generated_content(
    content_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> GeneratedContent:
    content = db.get(GeneratedContent, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Generated content not found")
    require_owned_chat(db, content.chat_id, user)
    return content


def _run_in_background(content_id: str, chat_id: str, mode: str, options: dict | None) -> None:
    """Runs on its own thread with its own DB session — SQLAlchemy sessions aren't
    thread-safe, so this must not reuse the request's session."""
    db = SessionLocal()
    try:
        content = db.get(GeneratedContent, content_id)
        chat = db.get(Chat, chat_id)
        sources = db.query(MaterialSource).filter(MaterialSource.chat_id == chat_id).all()
        generator = _GENERATORS[mode]

        def on_progress(current: int, total: int) -> None:
            content.progress_current = current
            content.progress_total = total
            db.commit()

        try:
            payload = generator.generate(chat, sources, options=options, on_progress=on_progress)
        except Exception as exc:
            content.status = "failed"
            content.error_message = str(exc)
            db.commit()
            return

        content.content_json = payload
        content.status = "ready"
        content.model_used = f"{get_settings().gemini_model}{_MODEL_USED_SUFFIX.get(mode, '')}"
        chat.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
