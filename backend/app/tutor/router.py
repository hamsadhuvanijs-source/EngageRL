from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.generation.text_combine import combine_source_text
from app.models.chat import Chat
from app.models.material_source import MaterialSource
from app.models.tutor_message import TutorMessage
from app.schemas.tutor import TutorMessageIn, TutorMessageOut, TutorReplyOut
from app.tutor.ollama_client import OllamaUnavailableError
from app.tutor.ollama_client import chat as ollama_chat

router = APIRouter(tags=["tutor"])

SYSTEM_PROMPT_TEMPLATE = """You are a friendly, encouraging study tutor helping a student understand their \
study material. Answer their questions clearly and simply, referencing the material below when it's \
relevant. Keep answers focused and conversational — a few sentences unless they ask for more detail.

STUDY MATERIAL:
{material}"""

HISTORY_LIMIT = 20
MATERIAL_CHAR_BUDGET = 6000


@router.get("/chats/{chat_id}/tutor/messages", response_model=list[TutorMessageOut])
def list_tutor_messages(chat_id: str, db: Session = Depends(get_db)) -> list[TutorMessage]:
    _get_chat(db, chat_id)
    return (
        db.query(TutorMessage).filter(TutorMessage.chat_id == chat_id).order_by(TutorMessage.created_at).all()
    )


@router.post("/chats/{chat_id}/tutor/messages", response_model=TutorReplyOut)
def send_tutor_message(chat_id: str, body: TutorMessageIn, db: Session = Depends(get_db)) -> TutorReplyOut:
    chat = _get_chat(db, chat_id)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")

    history = (
        db.query(TutorMessage)
        .filter(TutorMessage.chat_id == chat_id)
        .order_by(TutorMessage.created_at.desc())
        .limit(HISTORY_LIMIT)
        .all()
    )
    history.reverse()

    user_message = TutorMessage(chat_id=chat.id, role="user", content=body.content.strip())
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    sources = db.query(MaterialSource).filter(MaterialSource.chat_id == chat_id).all()
    material = combine_source_text(sources, total_budget=MATERIAL_CHAR_BUDGET) or "(no study material available yet)"

    messages = [{"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(material=material)}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": user_message.content})

    try:
        reply_text = ollama_chat(messages)
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    assistant_message = TutorMessage(chat_id=chat.id, role="assistant", content=reply_text)
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)

    return TutorReplyOut(user_message=user_message, assistant_message=assistant_message)


def _get_chat(db: Session, chat_id: str) -> Chat:
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat
