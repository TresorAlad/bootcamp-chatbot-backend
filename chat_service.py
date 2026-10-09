import json
from collections.abc import AsyncIterator

import httpx
from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from config import (
    NOTIFICATION_EVERY,
    NOTIFICATION_ROLE,
    NOTIFICATION_TEXT,
    RODIUMAI_URL,
    get_rodiumai_api_key,
    load_system_prompt,
)
from conversation import build_llm_history, load_messages
from database.db import SessionLocal
from database.models import Message


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_chat_reply(
    *,
    conversation_id: int,
    message: str,
    model: str,
    request: Request,
) -> AsyncIterator[str]:
    db = SessionLocal()
    try:
        rows = load_messages(db, conversation_id)
        history = build_llm_history(rows)
        next_seq = rows[-1].seq + 1 if rows else 1
        user_turn = {"role": "user", "content": message}
        llm_messages = [{"role": "system", "content": load_system_prompt()}, *history, user_turn]

        full_reply = ""
        usage: dict | None = None

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    RODIUMAI_URL,
                    headers={"Authorization": f"Bearer {get_rodiumai_api_key()}"},
                    json={
                        "model": model,
                        "messages": llm_messages,
                        "max_tokens": 512,
                        "stream": True,
                    },
                ) as response:
                    if response.status_code != 200:
                        yield _sse({"type": "error", "detail": "L'appel à l'API LLM a échoué."})
                        return

                    async for line in response.aiter_lines():
                        if await request.is_disconnected():
                            return

                        if not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            break

                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        if data.get("usage"):
                            usage = data["usage"]

                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        chunk = delta.get("content")
                        if chunk:
                            full_reply += chunk
                            yield _sse({"type": "delta", "content": chunk})

        except httpx.HTTPError:
            yield _sse({"type": "error", "detail": "L'appel à l'API LLM a échoué."})
            return

        if await request.is_disconnected():
            return

        if not full_reply.strip():
            yield _sse({"type": "error", "detail": "Réponse vide du modèle."})
            return

        notification = None
        db.add(
            Message(conversation_id=conversation_id, seq=next_seq, role="user", content=message)
        )
        db.add(
            Message(
                conversation_id=conversation_id,
                seq=next_seq + 1,
                role="assistant",
                content=full_reply,
            )
        )

        if (len(history) + 2) % NOTIFICATION_EVERY == 0:
            notification = NOTIFICATION_TEXT
            db.add(
                Message(
                    conversation_id=conversation_id,
                    seq=next_seq + 2,
                    role=NOTIFICATION_ROLE,
                    content=notification,
                )
            )

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            yield _sse(
                {
                    "type": "error",
                    "detail": "La conversation a été modifiée en parallèle, réessayez.",
                }
            )
            return

        yield _sse({"type": "done", "notification": notification, "usage": usage})
    finally:
        db.close()


def persist_note(db: Session, conversation_id: int, content: str) -> Message:
    rows = load_messages(db, conversation_id)
    next_seq = rows[-1].seq + 1 if rows else 1
    note = Message(
        conversation_id=conversation_id,
        seq=next_seq,
        role="note",
        content=content,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note
