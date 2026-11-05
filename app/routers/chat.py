"""Anonymous chat endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import idempotency
from app.clock import to_db, utcnow
from app.config import Settings
from app.schemas import MessageRequest
from app.routers.deps import current_actor, get_db, get_settings_dep
from app.services import chat_service

router = APIRouter(tags=["chat"])


@router.get("/claims/{claim_id}/messages")
def list_messages(
    claim_id: str,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    after: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    return chat_service.list_messages(session, actor, claim_id, after=after, limit=limit)


@router.post("/claims/{claim_id}/messages")
def send_message(
    claim_id: str,
    payload: MessageRequest,
    request: Request,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    body_payload = {"claim_id": claim_id, **payload.model_dump()}
    with session.begin():
        replay = idempotency.check(
            session, actor=actor, operation="chat.send", client_key=key, payload=body_payload
        )
        if replay:
            return JSONResponse(replay.body, status_code=replay.status_code, headers={"Idempotent-Replay": "true"})
        body = chat_service.send_message(session, settings, actor, claim_id, payload.text)
        idempotency.remember(
            session,
            actor=actor,
            operation="chat.send",
            client_key=key,
            payload=body_payload,
            status_code=201,
            body=body,
            now=to_db(utcnow()),
        )
    return JSONResponse(body, status_code=201)
