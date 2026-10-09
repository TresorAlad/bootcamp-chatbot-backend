from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chat_service import persist_note, stream_chat_reply
from config import NOTE_ROLE, get_allowed_models, get_default_model, validate_model
from conversation import build_llm_history, conversation_preview, list_conversations_query, load_messages
from database.db import get_db
from database.models import Conversation, Message

app = FastAPI(title="Study Buddy Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConversationResponse(BaseModel):
    conversation_id: int


class ConversationSummary(BaseModel):
    id: int
    created_at: datetime
    preview: str | None


class ChatRequest(BaseModel):
    conversation_id: int
    message: str = Field(min_length=1)
    model: str = Field(min_length=1)


class NoteRequest(BaseModel):
    content: str = Field(min_length=1)


class MessageResponse(BaseModel):
    seq: int
    role: str
    content: str
    created_at: datetime


class ModelsResponse(BaseModel):
    models: list[str]
    default: str


@app.get("/models", response_model=ModelsResponse)
def list_models() -> ModelsResponse:
    return ModelsResponse(models=get_allowed_models(), default=get_default_model())


@app.post("/conversations", status_code=201)
def create_conversation(db: Session = Depends(get_db)) -> ConversationResponse:
    conversation = Conversation()
    db.add(conversation)
    db.commit()
    return ConversationResponse(conversation_id=conversation.id)


@app.get("/conversations")
def list_conversations(db: Session = Depends(get_db)) -> list[ConversationSummary]:
    rows = list_conversations_query(db)
    return [
        ConversationSummary(
            id=conversation.id,
            created_at=conversation.created_at,
            preview=conversation_preview(content),
        )
        for conversation, content in rows
    ]


@app.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, db: Session = Depends(get_db)) -> list[MessageResponse]:
    return [
        MessageResponse(seq=m.seq, role=m.role, content=m.content, created_at=m.created_at)
        for m in load_messages(db, conversation_id)
    ]


@app.post("/conversations/{conversation_id}/notes", status_code=201)
def create_note(
    conversation_id: int, req: NoteRequest, db: Session = Depends(get_db)
) -> MessageResponse:
    try:
        note = persist_note(db, conversation_id, req.content.strip())
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="La conversation a été modifiée en parallèle, réessayez."
        ) from None
    return MessageResponse(
        seq=note.seq, role=note.role, content=note.content, created_at=note.created_at
    )


@app.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    try:
        validate_model(req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        stream_chat_reply(
            conversation_id=req.conversation_id,
            message=req.message.strip(),
            model=req.model,
            request=request,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


__all__ = ["app", "build_llm_history", "NOTE_ROLE"]
