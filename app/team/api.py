"""Team API transport and transaction boundaries."""

from collections.abc import Callable, Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from app import __version__
from app.clock import iso
from app.config import get_settings
from app.db import get_session
from app.errors import AppError
from app.team import claims, messages
from app.team.contracts import IdentityService, PostService, UserSummary, post_summary, user_summary
from app.team.demo import DemoIdentity, DemoPostService
from app.team.matching import find_matches
from app.team.models import Claim, ClaimMessage

async def require_json(request: Request) -> None:
    if request.method == "POST" and await request.body():
        media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type != "application/json":
            raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "请使用 application/json 提交数据")


router = APIRouter(tags=["认领"], dependencies=[Depends(require_json)])
demo_router = APIRouter(prefix="/demo", tags=["本地演示"], dependencies=[Depends(require_json)])
Db = Annotated[Session, Depends(get_session)]
Authorization = Annotated[str | None, Header()]
ResourceId = Annotated[str, StringConstraints(min_length=1, max_length=64)]
PathId = Annotated[str, Path(min_length=1, max_length=64)]
ClaimStatus = Literal["pending", "accepted", "rejected", "cancelled", "completed", "closed"]
RequiredNote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class StrictFields(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateClaim(StrictFields):
    post_id: ResourceId
    verification_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class AcceptClaim(StrictFields):
    decision_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class RejectClaim(StrictFields):
    decision_note: RequiredNote


class SendMessage(StrictFields):
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class Paging(StrictFields):
    page: Annotated[int, Query(ge=1)] = 1
    page_size: Annotated[int, Query(ge=1, le=100)] = 20


class ClaimFilters(Paging):
    role: Literal["applicant", "publisher"] = "applicant"
    status: ClaimStatus | None = None
    post_id: ResourceId | None = None


class MessageFilters(StrictFields):
    after_id: ResourceId | None = None
    limit: Annotated[int, Query(ge=1, le=100)] = 50


class MatchFilters(StrictFields):
    limit: Annotated[int, Query(ge=1, le=20)] = 10


class DemoLogin(StrictFields):
    actor: ResourceId


class DemoFilters(Paging):
    mine: Literal["true", "false"] = "false"


def ok(data: dict | None) -> dict:
    return {"code": "OK", "message": "操作成功", "data": data}


def page_result(items: list[dict], total: int, paging: Paging) -> dict:
    return {
        "items": items, "page": paging.page, "page_size": paging.page_size, "total": total,
        "total_pages": (total + paging.page_size - 1) // paging.page_size,
    }


def bearer(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or any(char.isspace() for char in token):
        raise AppError(401, "UNAUTHENTICATED", "请先登录", headers={"WWW-Authenticate": "Bearer"})
    return token


def actor(request: Request, session: Session, authorization: str | None) -> UserSummary:
    identity: IdentityService = request.app.state.identity
    if isinstance(identity, DemoIdentity):
        demo_enabled()
    return identity.require_user(session, bearer(authorization))


def demo_enabled() -> None:
    if not get_settings().demo_mode:
        raise AppError(404, "NOT_FOUND", "演示接口未开启")


def claim_views(request: Request, session: Session, records: list[Claim], *, lock: bool = False) -> list[dict]:
    identity: IdentityService = request.app.state.identity
    posts: PostService = request.app.state.posts
    users = identity.get_user_summaries(
        session, {user_id for record in records for user_id in (record.applicant_id, record.publisher_id)},
    ) if records else {}
    # A write already owns the Post lock. Read the current row even if a snapshot predates that lock.
    linked_posts = {
        post_id: posts.get_post_for_claim(session, post_id, lock=lock)
        for post_id in {record.post_id for record in records}
    }
    result = []
    for record in records:
        post = linked_posts[record.post_id]
        applicant = users.get(record.applicant_id)
        publisher = users.get(record.publisher_id)
        if post is None or applicant is None or publisher is None:
            raise AppError(500, "INTERNAL_ERROR", "关联信息不可用")
        result.append({
            "id": record.id, "post_id": record.post_id, "applicant_id": record.applicant_id,
            "verification_text": record.verification_text, "status": record.status,
            "decision_note": record.decision_note, "close_reason": record.close_reason,
            "applicant_confirmed_at": iso(record.applicant_confirmed_at),
            "publisher_confirmed_at": iso(record.publisher_confirmed_at),
            "created_at": iso(record.created_at), "updated_at": iso(record.updated_at),
            "applicant": user_summary(applicant), "publisher": user_summary(publisher),
            "post": {"id": post.id, "title": post.title, "post_type": post.post_type, "status": post.status},
        })
    return result


def message_views(request: Request, session: Session, records: list[ClaimMessage]) -> list[dict]:
    identity: IdentityService = request.app.state.identity
    users = identity.get_user_summaries(session, {record.sender_id for record in records}) if records else {}
    result = []
    for record in records:
        sender = users.get(record.sender_id)
        if sender is None:
            raise AppError(500, "INTERNAL_ERROR", "关联用户不可用")
        result.append({
            "id": str(record.id), "claim_id": record.claim_id, "sender_id": record.sender_id,
            "content": record.content, "created_at": iso(record.created_at), "sender": user_summary(sender),
        })
    return result


@router.post("/claims", status_code=201)
def create_claim(body: CreateClaim, request: Request, session: Db, authorization: Authorization = None) -> dict:
    with session.begin():
        user = actor(request, session, authorization)
        record = claims.create_claim(session, request.app.state.posts, user, body.post_id, body.verification_text)
        return ok(claim_views(request, session, [record], lock=True)[0])


@router.get("/claims/{claim_id}")
def get_claim(claim_id: PathId, request: Request, session: Db, authorization: Authorization = None) -> dict:
    record = claims.get_claim(session, actor(request, session, authorization), claim_id)
    return ok(claim_views(request, session, [record])[0])


@router.get("/users/me/claims")
def list_claims(
    filters: Annotated[ClaimFilters, Query()], request: Request, session: Db, authorization: Authorization = None,
) -> dict:
    records, total = claims.list_claims(
        session, actor(request, session, authorization), **filters.model_dump(),
    )
    return ok(page_result(claim_views(request, session, records), total, filters))


@router.post("/claims/{claim_id}/accept")
def accept_claim(
    claim_id: PathId, request: Request, session: Db,
    body: Annotated[AcceptClaim | None, Body()] = None, authorization: Authorization = None,
) -> dict:
    with session.begin():
        user = actor(request, session, authorization)
        record = claims.accept_claim(
            session, request.app.state.posts, user, claim_id, body.decision_note if body else None,
        )
        return ok(claim_views(request, session, [record], lock=True)[0])


@router.post("/claims/{claim_id}/reject")
def reject_claim(
    claim_id: PathId, body: RejectClaim, request: Request, session: Db, authorization: Authorization = None,
) -> dict:
    with session.begin():
        user = actor(request, session, authorization)
        record = claims.reject_claim(session, request.app.state.posts, user, claim_id, body.decision_note)
        return ok(claim_views(request, session, [record], lock=True)[0])


@router.post("/claims/{claim_id}/cancel")
def cancel_claim(
    claim_id: PathId, request: Request, session: Db,
    body: Annotated[StrictFields | None, Body()] = None, authorization: Authorization = None,
) -> dict:
    with session.begin():
        user = actor(request, session, authorization)
        record = claims.cancel_claim(session, request.app.state.posts, user, claim_id)
        return ok(claim_views(request, session, [record], lock=True)[0])


@router.post("/claims/{claim_id}/confirm-handover")
def confirm_handover(
    claim_id: PathId, request: Request, session: Db,
    body: Annotated[StrictFields | None, Body()] = None, authorization: Authorization = None,
) -> dict:
    with session.begin():
        user = actor(request, session, authorization)
        record = claims.confirm_handover(session, request.app.state.posts, user, claim_id)
        return ok(claim_views(request, session, [record], lock=True)[0])


@router.post("/claims/{claim_id}/messages", status_code=201)
def send_message(
    claim_id: PathId, body: SendMessage, request: Request, session: Db, authorization: Authorization = None,
) -> dict:
    with session.begin():
        user = actor(request, session, authorization)
        record = messages.send_message(session, request.app.state.posts, user, claim_id, body.content)
        return ok(message_views(request, session, [record])[0])


@router.get("/claims/{claim_id}/messages")
def list_messages(
    claim_id: PathId, filters: Annotated[MessageFilters, Query()], request: Request,
    session: Db, authorization: Authorization = None,
) -> dict:
    records, next_after_id, has_more = messages.list_messages(
        session, actor(request, session, authorization), claim_id, filters.after_id, filters.limit,
    )
    return ok({"items": message_views(request, session, records), "next_after_id": next_after_id, "has_more": has_more})


@router.get("/posts/{post_id}/matches")
def list_matches(
    post_id: PathId, filters: Annotated[MatchFilters, Query()], request: Request,
    session: Db, authorization: Authorization = None,
) -> dict:
    user = actor(request, session, authorization)
    return ok(find_matches(session, request.app.state.posts, user, post_id, filters.limit))


@demo_router.post("/token")
def demo_login(body: DemoLogin, request: Request) -> dict:
    demo_enabled()
    return ok(request.app.state.identity.issue(body.actor))


@demo_router.post("/logout")
def demo_logout(request: Request, authorization: Authorization = None) -> dict:
    demo_enabled()
    request.app.state.identity.logout(bearer(authorization))
    return ok(None)


@demo_router.get("/posts")
def demo_posts(
    filters: Annotated[DemoFilters, Query()], request: Request, session: Db, authorization: Authorization = None,
) -> dict:
    demo_enabled()
    user = actor(request, session, authorization) if filters.mine == "true" or authorization else None
    owner = user.id if user is not None and filters.mine == "true" else None
    records, total = request.app.state.posts.page(session, owner, filters.page, filters.page_size)
    return ok(page_result([post_summary(post) for post in records], total, filters))


def install_team_errors(app: FastAPI) -> None:
    def response(
        status: int, code: str, message: str, errors: dict | None = None, headers: dict | None = None,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status, headers=headers,
            content={"code": code, "message": message, "data": None, "errors": errors or {}},
        )

    @app.exception_handler(AppError)
    async def app_error(_: Request, error: AppError) -> JSONResponse:
        fields = {error.field: [error.message]} if error.field else {}
        headers = dict(error.headers)
        if error.retry_after_seconds is not None:
            headers.setdefault("Retry-After", str(error.retry_after_seconds))
        return response(error.status_code, error.code, error.message, fields, headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, error: RequestValidationError) -> JSONResponse:
        fields: dict[str, list[str]] = {}
        for item in error.errors():
            field = ".".join(str(part) for part in item["loc"][1:]) or str(item["loc"][0])
            fields.setdefault(field, []).append(item["msg"])
        return response(400, "VALIDATION_ERROR", "请检查填写内容", fields)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> JSONResponse:
        codes = {
            400: "VALIDATION_ERROR", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED", 413: "FILE_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE",
            429: "RATE_LIMITED",
        }
        if error.status_code >= 500:
            return response(error.status_code, "INTERNAL_ERROR", "服务器内部错误")
        return response(error.status_code, codes.get(error.status_code, "HTTP_ERROR"), str(error.detail),
                        headers=error.headers)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, error: Exception) -> JSONResponse:
        return response(500, "INTERNAL_ERROR", "服务器内部错误")


def create_team_app(
    *, identity: IdentityService | None = None, posts: PostService | None = None,
    session_dependency: Callable[[], Iterator[Session]] | None = None,
) -> FastAPI:
    """Build the API mounted at /api/v1. The host can also add its A and B routers here."""
    if (identity is None) != (posts is None):
        raise ValueError("Configure both identity and post adapters")
    app = FastAPI(title="校园失物招领 · 小组联调接口", version=__version__, redirect_slashes=False)
    app.state.identity = identity if identity is not None else DemoIdentity()
    app.state.posts = posts if posts is not None else DemoPostService()
    install_team_errors(app)
    app.include_router(router)
    if identity is None:
        app.include_router(demo_router)
    if session_dependency is not None:
        app.dependency_overrides[get_session] = session_dependency
    return app
