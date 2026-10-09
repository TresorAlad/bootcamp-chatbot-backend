from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from config import LLM_ROLES, PREVIEW_LENGTH
from database.models import Conversation, Message


def load_messages(db: Session, conversation_id: int) -> list[Message]:
    if db.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.seq)
    ).all()


def build_llm_history(rows: list[Message]) -> list[dict]:
    """Historique envoyé au LLM : uniquement user/assistant.

    Les rôles `system-notification` et `note` restent en base pour l'UI mais sont
    exclus ici : le modèle ne doit ni voir les rappels système ni les notes privées.
    """
    return [{"role": m.role, "content": m.content} for m in rows if m.role in LLM_ROLES]


def conversation_preview(content: str | None) -> str | None:
    return content[:PREVIEW_LENGTH] if content else None


def list_conversations_query(db: Session):
    return db.execute(
        select(Conversation, Message.content)
        .outerjoin(Message, and_(Message.conversation_id == Conversation.id, Message.seq == 1))
        .order_by(Conversation.id.desc())
    ).all()
