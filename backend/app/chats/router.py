from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_owned_chat
from app.ingestion.router import _source_to_out
from app.models.chat import Chat
from app.models.generated_content import GeneratedContent
from app.models.material_source import MaterialSource
from app.models.user import User
from app.schemas.chat import ChatDetailOut, ChatOut

router = APIRouter(tags=["chats"])


@router.post("/chats", response_model=ChatOut)
def create_chat(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Chat:
    chat = Chat(user_id=user.id, title=None)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


@router.get("/chats", response_model=list[ChatOut])
def list_chats(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Chat]:
    return db.query(Chat).filter(Chat.user_id == user.id).order_by(Chat.updated_at.desc()).all()


@router.get("/chats/{chat_id}", response_model=ChatDetailOut)
def get_chat(
    chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ChatDetailOut:
    chat = require_owned_chat(db, chat_id, user)

    sources = db.query(MaterialSource).filter(MaterialSource.chat_id == chat_id).order_by(MaterialSource.created_at).all()
    generations = (
        db.query(GeneratedContent).filter(GeneratedContent.chat_id == chat_id).order_by(GeneratedContent.created_at).all()
    )

    return ChatDetailOut(
        chat=ChatOut.model_validate(chat),
        sources=[_source_to_out(s) for s in sources],
        generations=list(generations),
    )
