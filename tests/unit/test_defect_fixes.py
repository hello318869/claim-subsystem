"""Regression tests for the v1.0 defects that need the real claim_test database.

Run with:  $env:RUN_DB_TESTS=1; python -m pytest tests/unit -q
Each test owns its own ``T-F-91xx`` item so cases cannot interfere; the module fixture
removes every row that references them before and after the run.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ["APP_ENV"] = "test"

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="requires the isolated claim_test database (RUN_DB_TESTS=1)",
)

ITEM_IDS = [f"T-F-{index}" for index in range(9101, 9114)]

SEED_ROWS = [
    ("T-F-9101", "published", "测试黑色背包", "bag", "图书馆二楼", "黑色背包 蓝色水杯 借书卡"),
    ("T-F-9102", "published", "测试灰色围巾", "clothing", "体育馆东门", "灰色围巾 末端有小洞"),
    ("T-F-9103", "published", "测试白色耳机", "electronics", "教学楼 A 座", "白色耳机 贴纸"),
    ("T-F-9104", "published", "测试校园卡", "card", "第二食堂", "校园卡 尾号 37"),
    ("T-F-9105", "published", "测试蓝色水杯", "cup", "图书馆三楼", "蓝色水杯 杯身划痕"),
    ("T-F-9106", "closed", "测试已关闭记录", "other", "未知", "已关闭 不应可认领"),
    ("T-F-9107", "published", "测试充电器", "electronics", "实验楼", "白色充电器 线材破损"),
    ("T-F-9108", "published", "测试雨伞", "rain", "图书馆门口", "黑色长柄雨伞 弯钩伞柄"),
    ("T-F-9109", "published", "测试笔记本", "stationery", "教学楼 B 座", "蓝色笔记本 内页有名字缩写"),
    ("T-F-9110", "published", "测试水杯", "cup", "体育馆", "透明水杯 杯盖有裂痕"),
    ("T-F-9111", "published", "测试钥匙", "key", "宿舍楼下", "单把钥匙 挂蓝色钥匙扣"),
    ("T-F-9112", "published", "测试手套", "clothing", "操场", "灰色手套 左手"),
    ("T-F-9113", "published", "测试眼镜", "other", "图书馆一楼", "黑框眼镜 镜腿松动"),
]


def _clean() -> None:
    from sqlalchemy import delete, select

    from app.db import session_scope
    from app.models import (
        AuditEvent,
        Claim,
        HandoverCode,
        IdempotencyRecord,
        ItemApproval,
        ListingSnapshot,
        Message,
    )

    with session_scope() as session:
        claim_ids = list(session.execute(select(Claim.id).where(Claim.item_id.in_(ITEM_IDS))).scalars())
        if claim_ids:
            session.execute(delete(Message).where(Message.claim_id.in_(claim_ids)))
            session.execute(delete(HandoverCode).where(HandoverCode.claim_id.in_(claim_ids)))
            session.execute(delete(AuditEvent).where(AuditEvent.claim_id.in_(claim_ids)))
            session.execute(delete(Claim).where(Claim.id.in_(claim_ids)))
        session.execute(delete(ItemApproval).where(ItemApproval.item_id.in_(ITEM_IDS)))
        session.execute(delete(ListingSnapshot).where(ListingSnapshot.item_id.in_(ITEM_IDS)))
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id.in_(["alice", "bob", "finder"])))


def _seed() -> None:
    from app.clock import to_db, utcnow
    from app.db import session_scope
    from app.models import ListingSnapshot

    now = utcnow()
    with session_scope() as session:
        for item_id, status, title, category, location, description in SEED_ROWS:
            session.add(
                ListingSnapshot(
                    item_id=item_id,
                    kind="found",
                    title=title,
                    category=category,
                    occurred_at=to_db(now),
                    location=location,
                    description=description,
                    status=status,
                    publisher_user_id="finder",
                    origin="demo",
                    synced_at=to_db(now),
                )
            )


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    _clean()
    _seed()
    with TestClient(create_app()) as test_client:
        yield test_client
    _clean()


def _token(client, actor: str) -> str:
    response = client.post("/v1/demo/token", json={"actor": actor})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create(client, token: str, item_id: str, evidence: str = "证据") -> dict:
    response = client.post("/v1/claims", json={"item_id": item_id, "evidence_text": evidence}, headers=_auth(token))
    assert response.status_code in (200, 201), response.text
    return response.json()


# --- D1: DISPUTED is read-only ---------------------------------------------------


def test_disputed_claim_rejects_new_messages(client):
    alice, finder = _token(client, "alice"), _token(client, "finder")
    claim_id = _create(client, alice, "T-F-9102")["id"]
    assert client.post(f"/v1/claims/{claim_id}/approve", headers=_auth(finder)).status_code == 200
    disputed = client.post(f"/v1/claims/{claim_id}/dispute", json={"reason": "地点不一致"}, headers=_auth(alice))
    assert disputed.json()["status"] == "DISPUTED"

    blocked = client.post(f"/v1/claims/{claim_id}/messages", json={"text": "补充一条"}, headers=_auth(alice))
    assert blocked.status_code == 409
    assert client.get(f"/v1/claims/{claim_id}/messages", headers=_auth(alice)).status_code == 200


# --- D2: concurrency -------------------------------------------------------------


def test_same_idempotency_key_concurrent_create_never_500(client):
    alice = _token(client, "alice")
    payload = {"item_id": "T-F-9103", "evidence_text": "耳机盒有贴纸"}
    headers = {**_auth(alice), "Idempotency-Key": "race-key-9103"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post("/v1/claims", json=payload, headers=headers), range(2)))

    codes = [response.status_code for response in responses]
    assert all(code in (200, 201) for code in codes), codes
    assert len({response.json()["id"] for response in responses}) == 1


def test_different_keys_concurrent_create_yields_one_pending(client):
    alice = _token(client, "alice")
    payload = {"item_id": "T-F-9104", "evidence_text": "尾号 37"}

    def send(index: int):
        return client.post(
            "/v1/claims", json=payload, headers={**_auth(alice), "Idempotency-Key": f"distinct-{index}"}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))

    assert all(response.status_code in (200, 201) for response in responses), [
        response.status_code for response in responses
    ]
    assert len({response.json()["id"] for response in responses}) == 1

    from sqlalchemy import func, select

    from app.db import session_scope
    from app.models import Claim

    with session_scope() as session:
        count = session.execute(
            select(func.count())
            .select_from(Claim)
            .where(Claim.item_id == "T-F-9104", Claim.status == "PENDING")
        ).scalar_one()
    assert count == 1


def test_locked_read_refreshes_stale_identity(client):
    from sqlalchemy import update

    from app.db import session_scope
    from app.models import Claim
    from app.repos import claim_repo

    alice = _token(client, "alice")
    claim_id = _create(client, alice, "T-F-9105")["id"]

    with session_scope() as stale:
        loaded = claim_repo.get(stale, claim_id)
        assert loaded is not None and loaded.status == "PENDING"
        with session_scope() as writer:
            writer.execute(update(Claim).where(Claim.id == claim_id).values(status="DISPUTED"))
        refreshed = claim_repo.lock(stale, claim_id)
        assert refreshed is not None
        assert refreshed.status == "DISPUTED", "locking read must not return the pre-lock snapshot"
        stale.rollback()


# --- D4: whitespace --------------------------------------------------------------


def test_whitespace_only_bodies_are_422(client):
    alice, finder = _token(client, "alice"), _token(client, "finder")
    blank_claim = client.post(
        "/v1/claims", json={"item_id": "T-F-9101", "evidence_text": "   "}, headers=_auth(alice)
    )
    assert blank_claim.status_code == 422
    assert blank_claim.json()["field"] == "evidence_text"

    claim_id = _create(client, alice, "T-F-9101")["id"]
    blank_message = client.post(f"/v1/claims/{claim_id}/messages", json={"text": "\n\t"}, headers=_auth(alice))
    assert blank_message.status_code == 422
    assert blank_message.json()["field"] == "text"

    blank_reject = client.post(f"/v1/claims/{claim_id}/reject", json={"reason": "  "}, headers=_auth(finder))
    assert blank_reject.status_code == 422
    assert blank_reject.json()["field"] == "reason"


# --- D6: reset after the absolute deadline persists EXPIRED ----------------------


def test_reset_after_deadline_persists_expired(client):
    from datetime import timedelta

    from sqlalchemy import update

    from app.clock import to_db, utcnow
    from app.db import session_scope
    from app.models import Claim

    alice, finder = _token(client, "alice"), _token(client, "finder")
    claim_id = _create(client, alice, "T-F-9107")["id"]
    assert client.post(f"/v1/claims/{claim_id}/approve", headers=_auth(finder)).status_code == 200

    with session_scope() as session:
        session.execute(
            update(Claim).where(Claim.id == claim_id).values(handover_deadline=to_db(utcnow() - timedelta(hours=1)))
        )

    reset = client.post(f"/v1/claims/{claim_id}/handover/reset", json={"reason": "过期"}, headers=_auth(alice))
    assert reset.status_code == 410
    assert reset.json()["code"] == "code_expired"

    detail = client.get(f"/v1/claims/{claim_id}", headers=_auth(alice))
    assert detail.json()["status"] == "EXPIRED", "EXPIRED must survive the transaction"


# --- D7: message cursor ----------------------------------------------------------


def test_cursor_keeps_messages_written_in_the_same_second(client):
    import uuid

    from app.clock import to_db, utcnow
    from app.db import session_scope
    from app.models import Message

    alice = _token(client, "alice")
    claim_id = _create(client, alice, "T-F-9111", evidence="游标测试")["id"]
    stamp = to_db(utcnow().replace(microsecond=0))

    with session_scope() as session:
        for index in range(3):
            session.add(
                Message(
                    id=str(uuid.uuid4()),
                    claim_id=claim_id,
                    sender_role="applicant",
                    body=f"同秒消息 {index}",
                    created_at=stamp,
                )
            )

    first_page = client.get(f"/v1/claims/{claim_id}/messages", params={"limit": 2}, headers=_auth(alice)).json()
    assert len(first_page["items"]) == 2
    assert first_page["next_after"]

    second_page = client.get(
        f"/v1/claims/{claim_id}/messages",
        params={"limit": 2, "after": first_page["next_after"]},
        headers=_auth(alice),
    ).json()
    assert len(second_page["items"]) == 1, "messages sharing the cursor timestamp must not be skipped"
    assert len({item["id"] for item in first_page["items"] + second_page["items"]}) == 3


def test_foreign_cursor_is_rejected(client):
    alice = _token(client, "alice")
    first = _create(client, alice, "T-F-9112", evidence="会话一")["id"]
    second = _create(client, alice, "T-F-9113", evidence="会话二")["id"]
    message = client.post(f"/v1/claims/{second}/messages", json={"text": "另一会话"}, headers=_auth(alice)).json()

    response = client.get(f"/v1/claims/{first}/messages", params={"after": message["id"]}, headers=_auth(alice))
    assert response.status_code == 422


# --- D8: status gate and confirmation flags --------------------------------------


def test_unpublished_snapshot_is_not_claimable(client):
    alice = _token(client, "alice")
    response = client.post(
        "/v1/claims", json={"item_id": "T-F-9106", "evidence_text": "已关闭记录"}, headers=_auth(alice)
    )
    assert response.status_code == 422
    assert response.json()["code"] == "not_claimable"


def test_completed_claim_keeps_confirmation_history_and_disputed_clears_it(client):
    alice, finder = _token(client, "alice"), _token(client, "finder")

    done = _create(client, alice, "T-F-9108", evidence="完成用例")["id"]
    assert client.post(f"/v1/claims/{done}/approve", headers=_auth(finder)).status_code == 200
    alice_code = client.get(f"/v1/claims/{done}/code", headers=_auth(alice)).json()["code"]
    finder_code = client.get(f"/v1/claims/{done}/code", headers=_auth(finder)).json()["code"]
    client.post(f"/v1/claims/{done}/handover/confirm", json={"code": finder_code}, headers=_auth(alice))
    client.post(f"/v1/claims/{done}/handover/confirm", json={"code": alice_code}, headers=_auth(finder))

    completed = client.get(f"/v1/claims/{done}", headers=_auth(alice)).json()
    assert completed["status"] == "COMPLETED"
    assert completed["confirmed_by_me"] is True and completed["confirmed_by_counterpart"] is True

    disputed = _create(client, alice, "T-F-9109", evidence="争议用例")["id"]
    assert client.post(f"/v1/claims/{disputed}/approve", headers=_auth(finder)).status_code == 200
    client.post(f"/v1/claims/{disputed}/dispute", json={"reason": "争议"}, headers=_auth(alice))
    detail = client.get(f"/v1/claims/{disputed}", headers=_auth(alice)).json()
    assert detail["status"] == "DISPUTED"
    assert detail["confirmed_by_me"] is False and detail["confirmed_by_counterpart"] is False


def test_dispute_export_reports_message_totals(client):
    alice, finder = _token(client, "alice"), _token(client, "finder")
    claim_id = _create(client, alice, "T-F-9110", evidence="导出用例")["id"]
    assert client.post(f"/v1/claims/{claim_id}/approve", headers=_auth(finder)).status_code == 200
    client.post(f"/v1/claims/{claim_id}/messages", json={"text": "第一条"}, headers=_auth(alice))
    client.post(f"/v1/claims/{claim_id}/dispute", json={"reason": "导出"}, headers=_auth(alice))

    export = client.get(f"/v1/claims/{claim_id}/dispute-export", headers=_auth(alice)).json()
    assert export["messages_total"] >= 1
    assert export["messages_truncated"] is False
    assert len(export["messages"]) == export["messages_total"]
