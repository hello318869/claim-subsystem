"""Claim endpoints. Every write is wrapped in one transaction with the fixed lock order."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import idempotency
from app.clock import to_db, utcnow
from app.config import Settings
from app.routers.deps import current_actor, get_db, get_settings_dep
from app.schemas import ClaimCreateRequest, HandoverConfirmRequest, ReasonRequest, ResetRequest
from app.services import claim_service, handover_service

router = APIRouter(tags=["claims"])

REPLAY_HEADER = {"Idempotent-Replay": "true"}


@router.post("/claims")
def create_claim(
    payload: ClaimCreateRequest,
    request: Request,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    body_payload = payload.model_dump()
    now = to_db(utcnow())
    with session.begin():
        replay = idempotency.claim(
            session, settings, actor=actor, operation="claim.create", client_key=key, payload=body_payload, now=now
        )
        if replay:
            return JSONResponse(replay.body, status_code=replay.status_code, headers=REPLAY_HEADER)
        status_code, body = claim_service.create(session, settings, actor, body_payload)
        idempotency.complete(
            session,
            actor=actor,
            operation="claim.create",
            client_key=key,
            status_code=status_code,
            body=body,
        )
    return JSONResponse(body, status_code=status_code)


@router.get("/claims")
def list_claims(
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    role: Annotated[str, Query(pattern="^(applicant|finder|all)$")] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    return claim_service.list_claims(session, settings, actor, role=role, page=page, page_size=page_size)


@router.get("/claims/{claim_id}")
def get_claim(
    claim_id: str,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> dict:
    return claim_service.get_detail(session, settings, actor, claim_id)


@router.post("/claims/{claim_id}/withdraw")
def withdraw_claim(
    claim_id: str,
    request: Request,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    payload = {"claim_id": claim_id}
    with session.begin():
        replay = idempotency.claim(
            session,
            settings,
            actor=actor,
            operation="claim.withdraw",
            client_key=key,
            payload=payload,
            now=to_db(utcnow()),
        )
        if replay:
            return JSONResponse(replay.body, status_code=replay.status_code, headers=REPLAY_HEADER)
        body = claim_service.withdraw(session, actor, claim_id)
        idempotency.complete(
            session, actor=actor, operation="claim.withdraw", client_key=key, status_code=200, body=body
        )
    return JSONResponse(body, status_code=200)


@router.post("/claims/{claim_id}/approve")
def approve_claim(
    claim_id: str,
    request: Request,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    payload = {"claim_id": claim_id}
    with session.begin():
        replay = idempotency.claim(
            session,
            settings,
            actor=actor,
            operation="claim.approve",
            client_key=key,
            payload=payload,
            now=to_db(utcnow()),
        )
        if replay:
            return JSONResponse(replay.body, status_code=replay.status_code, headers=REPLAY_HEADER)
        body = claim_service.approve(session, settings, actor, claim_id)
        idempotency.complete(
            session, actor=actor, operation="claim.approve", client_key=key, status_code=200, body=body
        )
    return JSONResponse(body, status_code=200)


@router.post("/claims/{claim_id}/reject")
def reject_claim(
    claim_id: str,
    payload: ReasonRequest,
    request: Request,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    body_payload = {"claim_id": claim_id, **payload.model_dump()}
    with session.begin():
        replay = idempotency.claim(
            session,
            settings,
            actor=actor,
            operation="claim.reject",
            client_key=key,
            payload=body_payload,
            now=to_db(utcnow()),
        )
        if replay:
            return JSONResponse(replay.body, status_code=replay.status_code, headers=REPLAY_HEADER)
        body = claim_service.reject(session, actor, claim_id, payload.reason)
        idempotency.complete(
            session, actor=actor, operation="claim.reject", client_key=key, status_code=200, body=body
        )
    return JSONResponse(body, status_code=200)


@router.post("/claims/{claim_id}/dispute")
def dispute_claim(
    claim_id: str,
    payload: ReasonRequest,
    request: Request,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    body_payload = {"claim_id": claim_id, **payload.model_dump()}
    with session.begin():
        replay = idempotency.claim(
            session,
            settings,
            actor=actor,
            operation="claim.dispute",
            client_key=key,
            payload=body_payload,
            now=to_db(utcnow()),
        )
        if replay:
            return JSONResponse(replay.body, status_code=replay.status_code, headers=REPLAY_HEADER)
        body = claim_service.dispute(session, actor, claim_id, payload.reason)
        idempotency.complete(
            session, actor=actor, operation="claim.dispute", client_key=key, status_code=200, body=body
        )
    return JSONResponse(body, status_code=200)


@router.get("/claims/{claim_id}/dispute-export")
def export_dispute(
    claim_id: str,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
) -> dict:
    return claim_service.dispute_export(session, actor, claim_id)


@router.get("/claims/{claim_id}/code")
def get_handover_code(
    claim_id: str,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> dict:
    return handover_service.get_code(session, settings, actor, claim_id)


@router.post("/claims/{claim_id}/handover/confirm")
def confirm_handover(
    claim_id: str,
    payload: HandoverConfirmRequest,
    request: Request,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    body_payload = {"claim_id": claim_id, "code": payload.code}
    with session.begin():
        replay = idempotency.claim(
            session,
            settings,
            actor=actor,
            operation="handover.confirm",
            client_key=key,
            payload=body_payload,
            now=to_db(utcnow()),
        )
        if replay:
            return JSONResponse(replay.body, status_code=replay.status_code, headers=REPLAY_HEADER)
        status_code, body = handover_service.confirm(session, settings, actor, claim_id, payload.code)
        idempotency.complete(
            session,
            actor=actor,
            operation="handover.confirm",
            client_key=key,
            status_code=status_code,
            body=body,
        )
    return JSONResponse(body, status_code=status_code)


@router.post("/claims/{claim_id}/handover/reset")
def reset_handover(
    claim_id: str,
    payload: ResetRequest,
    request: Request,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    body_payload = {"claim_id": claim_id, **payload.model_dump()}
    with session.begin():
        replay = idempotency.claim(
            session,
            settings,
            actor=actor,
            operation="handover.reset",
            client_key=key,
            payload=body_payload,
            now=to_db(utcnow()),
        )
        if replay:
            return JSONResponse(replay.body, status_code=replay.status_code, headers=REPLAY_HEADER)
        status_code, body = handover_service.reset(session, settings, actor, claim_id, payload.reason)
        idempotency.complete(
            session,
            actor=actor,
            operation="handover.reset",
            client_key=key,
            status_code=status_code,
            body=body,
        )
    return JSONResponse(body, status_code=status_code)
