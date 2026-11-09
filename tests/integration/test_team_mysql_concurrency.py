"""Exercise the team API transaction boundary against the isolated MySQL database."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.clock import to_db, utcnow
from app.errors import AppError
from app.team.api import create_team_app
from app.team.contracts import Post, UserSummary
from app.team.demo import DEMO_USERS, DemoPost, DemoPostService
from app.team.models import Claim, ClaimMessage
from claimtest.env import TEST_DB_NAME, TestEnv as IsolatedTestEnv


pytestmark = pytest.mark.integration
_PROOF = "合成测试记录的钥匙套背面刻有三颗星。"


@pytest.fixture(scope="module")
def team_sessions(test_env: IsolatedTestEnv, db_identity) -> Iterator[sessionmaker[Session]]:
    url = make_url(test_env.test_database_url).set(drivername="mysql+pymysql")
    engine = create_engine(url, connect_args={"connect_timeout": 5, "read_timeout": 20, "write_timeout": 20})
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT DATABASE()")) == TEST_DB_NAME
            schema = inspect(connection)
            missing = [
                model.__tablename__ for model in (DemoPost, Claim, ClaimMessage)
                if not schema.has_table(model.__tablename__)
            ]
            assert not missing, f"Initialize team tables in claim_test before running: {missing}"
        yield sessionmaker(engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture
def team_post(team_sessions: sessionmaker[Session]) -> Iterator[str]:
    post_id = f"team-test-{uuid4().hex}"
    now = to_db(utcnow())
    with team_sessions.begin() as session:
        session.add(DemoPost(
            id=post_id, post_type="lost", title="MySQL 并发测试合成信息", publisher_id="finder",
            category_id="keys", category_name="钥匙", campus_id="main", campus_name="主校区",
            location_id="library", location_name="图书馆", status="open",
            occurred_at=now, created_at=now, updated_at=now,
        ))
    try:
        yield post_id
    finally:
        with team_sessions.begin() as session:
            own_claims = select(Claim.id).where(Claim.post_id == post_id)
            session.execute(delete(ClaimMessage).where(ClaimMessage.claim_id.in_(own_claims)))
            session.execute(delete(Claim).where(Claim.post_id == post_id))
            session.execute(delete(DemoPost).where(DemoPost.id == post_id))


class _FixtureIdentity:
    """Map synthetic bearer values in the in-process test app only."""

    def require_user(self, session: Session, token: str) -> UserSummary:
        user = DEMO_USERS.get(token)
        if user is None:
            raise AppError(401, "UNAUTHENTICATED", "未知的测试身份")
        return user

    def get_user_summaries(self, session: Session, user_ids: set[str]) -> dict[str, UserSummary]:
        return {user_id: DEMO_USERS[user_id] for user_id in user_ids}


@pytest.fixture
def team_service(team_sessions: sessionmaker[Session]) -> FastAPI:
    def session_dependency() -> Iterator[Session]:
        with team_sessions() as session:
            yield session

    return create_team_app(
        identity=_FixtureIdentity(), posts=DemoPostService(), session_dependency=session_dependency,
    )


@pytest.fixture
def team_api(team_service: FastAPI) -> FastAPI:
    host = FastAPI()
    host.mount("/api/v1", team_service)
    return host


def _post(app: FastAPI, actor: str, path: str, body: dict | None = None) -> httpx.Response:
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(f"/api/v1{path}", headers={"Authorization": f"Bearer {actor}"}, json=body)


def _application(post_id: str) -> dict:
    return {"post_id": post_id, "verification_text": _PROOF}


def _apply(app: FastAPI, post_id: str, actor: str) -> str:
    response = _post(app, actor, "/claims", _application(post_id))
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class _SynchronizedPosts(DemoPostService):
    def __init__(self) -> None:
        self.at_lock = Barrier(2, timeout=10)

    def get_post_for_claim(self, session: Session, post_id: str, *, lock: bool = False) -> Post | None:
        if lock and not session.info.get("synchronized_post_lock"):
            session.info["synchronized_post_lock"] = True
            self.at_lock.wait()
        return super().get_post_for_claim(session, post_id, lock=lock)


def _race(
    app: FastAPI, left: tuple[str, str, dict | None], right: tuple[str, str, dict | None],
) -> list[httpx.Response]:
    # Both transactions reach B's locking read before either can acquire the row lock.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_post, app, *request) for request in (left, right)]
        return [future.result(timeout=35) for future in futures]


def test_same_actor_concurrent_applications_create_only_one_row(team_api, team_service, team_post, team_sessions):
    team_service.state.posts = _SynchronizedPosts()
    request = ("alice", "/claims", _application(team_post))
    responses = _race(team_api, request, request)

    assert sorted(response.status_code for response in responses) == [201, 409], [r.text for r in responses]
    winner = next(response.json()["data"] for response in responses if response.status_code == 201)
    conflict = next(response.json() for response in responses if response.status_code == 409)
    assert conflict["code"] == "DUPLICATE_RESOURCE"
    with team_sessions() as session:
        rows = session.scalars(select(Claim).where(Claim.post_id == team_post)).all()
        assert [(row.id, row.applicant_id, row.status) for row in rows] == [(winner["id"], "alice", "pending")]
        assert session.get(DemoPost, team_post).status == "open"


def test_concurrent_accepts_reserve_post_and_close_only_the_loser(team_api, team_service, team_post, team_sessions):
    alice = _apply(team_api, team_post, "alice")
    bob = _apply(team_api, team_post, "bob")
    team_service.state.posts = _SynchronizedPosts()
    responses = _race(
        team_api, ("finder", f"/claims/{alice}/accept", None), ("finder", f"/claims/{bob}/accept", None),
    )

    assert sorted(response.status_code for response in responses) == [200, 409], [r.text for r in responses]
    winner = next(response.json()["data"] for response in responses if response.status_code == 200)
    conflict = next(response.json() for response in responses if response.status_code == 409)
    assert conflict["code"] == "STATE_CONFLICT"
    loser = bob if winner["id"] == alice else alice
    with team_sessions() as session:
        rows = session.scalars(select(Claim).where(Claim.post_id == team_post)).all()
        assert {row.id: (row.status, row.close_reason) for row in rows} == {
            winner["id"]: ("accepted", None), loser: ("closed", "another_claim_accepted"),
        }
        assert session.get(DemoPost, team_post).status == "in_handover"


class _FailAfterReserve(DemoPostService):
    def __init__(self) -> None:
        self.staged: tuple[str, set[str]] | None = None

    def set_handover_state(self, session: Session, post_id: str, transition: str) -> Post:
        assert transition == "reserve"
        post = super().set_handover_state(session, post_id, transition)
        statuses = set(session.scalars(select(Claim.status).where(Claim.post_id == post_id)))
        self.staged = (post.status, statuses)
        raise RuntimeError("Injected B transition failure after flush")


def test_adapter_failure_rolls_back_both_post_and_claim_writes(team_api, team_service, team_post, team_sessions):
    winner = _apply(team_api, team_post, "alice")
    loser = _apply(team_api, team_post, "bob")
    failure = _FailAfterReserve()
    team_service.state.posts = failure
    path = f"/claims/{winner}/accept"
    response = _post(team_api, "finder", path, {"decision_note": "合成回滚场景"})

    assert failure.staged == ("in_handover", {"accepted", "closed"})
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "INTERNAL_ERROR"
    with team_sessions() as session:
        assert session.get(DemoPost, team_post).status == "open"
        rows = session.scalars(select(Claim).where(Claim.post_id == team_post)).all()
        assert {row.id: (row.status, row.close_reason, row.decision_note) for row in rows} == {
            winner: ("pending", None, None), loser: ("pending", None, None),
        }

    team_service.state.posts = DemoPostService()
    retry = _post(team_api, "finder", path)
    assert retry.status_code == 200, retry.text
    assert retry.json()["data"]["status"] == "accepted"


def test_concurrent_confirmations_complete_both_post_and_claim(team_api, team_service, team_post, team_sessions):
    claim_id = _apply(team_api, team_post, "alice")
    accepted = _post(team_api, "finder", f"/claims/{claim_id}/accept")
    assert accepted.status_code == 200, accepted.text
    team_service.state.posts = _SynchronizedPosts()
    path = f"/claims/{claim_id}/confirm-handover"
    responses = _race(team_api, ("alice", path, None), ("finder", path, None))

    assert [response.status_code for response in responses] == [200, 200], [r.text for r in responses]
    assert {
        (data["status"], data["post"]["status"])
        for data in (response.json()["data"] for response in responses)
    } == {("accepted", "in_handover"), ("completed", "completed")}
    with team_sessions() as session:
        claim = session.get(Claim, claim_id)
        post = session.get(DemoPost, team_post)
        assert claim.status == post.status == "completed"
        assert claim.applicant_confirmed_at is not None and claim.publisher_confirmed_at is not None
        assert claim.completed_at is not None and post.completed_at is not None
