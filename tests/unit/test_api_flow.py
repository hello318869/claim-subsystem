"""End-to-end contract smoke test against the isolated claim_test database.

Skipped by default; run with:  $env:RUN_DB_TESTS=1; python -m pytest tests/unit -q

The fixture owns three throw-away item ids (T-F-9001..9003) and removes them, plus every
row that references them, before and after the module runs. Seeded demo data is untouched.
"""

from __future__ import annotations

import os

import pytest

os.environ["APP_ENV"] = "test"

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="requires the isolated claim_test database (RUN_DB_TESTS=1)",
)

ITEM_IDS = ["T-F-9001", "T-F-9002", "T-F-9003", "T-F-9004", "T-F-9005", "T-L-9001"]


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
        claim_ids = [
            row for row in session.execute(select(Claim.id).where(Claim.item_id.in_(ITEM_IDS))).scalars()
        ]
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
    rows = [
        ("T-F-9001", "found", "测试黑色双肩包", "bag", "图书馆二楼", "黑色双肩包 蓝色水杯", "finder"),
        ("T-F-9002", "found", "测试灰色围巾", "clothing", "体育馆东门", "灰色针织围巾", "finder"),
        ("T-F-9003", "found", "测试白色耳机", "electronics", "教学楼 A 座", "白色无线耳机", "finder"),
        ("T-F-9004", "found", "测试蓝色保温杯", "cup", "图书馆三楼", "蓝色保温杯 杯身有划痕", "finder"),
        ("T-F-9005", "found", "测试校园卡", "card", "第二食堂", "校园卡 尾号 37", "finder"),
        ("T-L-9001", "lost", "测试黑色双肩包丢失", "bag", "图书馆二楼", "黑色双肩包 蓝色水杯 借书卡", "alice"),
    ]
    with session_scope() as session:
        for item_id, kind, title, category, location, description, owner in rows:
            session.add(
                ListingSnapshot(
                    item_id=item_id,
                    kind=kind,
                    title=title,
                    category=category,
                    occurred_at=to_db(now),
                    location=location,
                    description=description,
                    status="published",
                    publisher_user_id=owner,
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


def test_health_and_demo_disabled_flag(client):
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["database"] == "ok" and body["demo_mode"] is True


def test_full_claim_and_handover_flow(client):
    alice, finder, outsider = _token(client, "alice"), _token(client, "finder"), _token(client, "outsider")

    listing = client.get("/v1/listings/T-F-9001", headers=_auth(alice)).json()
    assert listing["claimable"] is True
    assert "publisher_id" not in listing

    payload = {"item_id": "T-F-9001", "evidence_text": "包里有蓝色水杯", "item_number": "ASSET-2026-0042"}
    created = client.post("/v1/claims", json=payload, headers={**_auth(alice), "Idempotency-Key": "k1"})
    assert created.status_code == 201, created.text
    claim_id = created.json()["id"]

    replay = client.post("/v1/claims", json=payload, headers={**_auth(alice), "Idempotency-Key": "k1"})
    assert replay.status_code == 201 and replay.json()["id"] == claim_id
    assert replay.headers.get("Idempotent-Replay") == "true"

    conflict = client.post(
        "/v1/claims",
        json={**payload, "evidence_text": "改了内容"},
        headers={**_auth(alice), "Idempotency-Key": "k1"},
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"

    assert client.get(f"/v1/claims/{claim_id}", headers=_auth(outsider)).status_code == 403
    assert client.post(f"/v1/claims/{claim_id}/approve", headers=_auth(alice)).status_code == 403

    approved = client.post(f"/v1/claims/{claim_id}/approve", headers=_auth(finder))
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED", approved.text

    alice_code = client.get(f"/v1/claims/{claim_id}/code", headers=_auth(alice)).json()["code"]
    finder_code = client.get(f"/v1/claims/{claim_id}/code", headers=_auth(finder)).json()["code"]
    assert alice_code != finder_code and len(alice_code) == 8

    blocked = client.post(
        f"/v1/claims/{claim_id}/messages", json={"text": "我电话 13812345678"}, headers=_auth(alice)
    )
    assert blocked.status_code == 422 and blocked.json()["code"] == "contact_info_blocked"

    sent = client.post(f"/v1/claims/{claim_id}/messages", json={"text": "好的，食堂门口见"}, headers=_auth(alice))
    assert sent.status_code == 201
    assert "sender_id" not in sent.json()

    inbox = client.get(f"/v1/claims/{claim_id}/messages", headers=_auth(finder)).json()
    assert inbox["items"] and inbox["items"][0]["is_mine"] is False
    assert "next_after" in inbox

    wrong = client.post(f"/v1/claims/{claim_id}/handover/confirm", json={"code": "00000000"}, headers=_auth(alice))
    assert wrong.status_code == 422 and wrong.json()["code"] == "invalid_code"

    first = client.post(f"/v1/claims/{claim_id}/handover/confirm", json={"code": finder_code}, headers=_auth(alice))
    assert first.status_code == 200 and first.json()["confirmed_by_me"] is True
    assert first.json()["confirmed_by_counterpart"] is False

    second = client.post(f"/v1/claims/{claim_id}/handover/confirm", json={"code": alice_code}, headers=_auth(finder))
    assert second.status_code == 200 and second.json()["status"] == "COMPLETED"

    closed = client.post(
        f"/v1/claims/{claim_id}/messages", json={"text": "完成后再发一条"}, headers=_auth(alice)
    )
    assert closed.status_code == 409

    export = client.get(f"/v1/claims/{claim_id}/dispute-export", headers=_auth(alice)).json()
    text = str(export)
    assert "applicant_id" not in text and "publisher_user_id" not in text


def test_second_approval_is_rejected(client):
    alice, bob, finder = _token(client, "alice"), _token(client, "bob"), _token(client, "finder")
    payload = {"item_id": "T-F-9002", "evidence_text": "围巾末端有小洞"}

    first = client.post("/v1/claims", json=payload, headers=_auth(alice)).json()["id"]
    second = client.post("/v1/claims", json={**payload, "evidence_text": "也是我的围巾"}, headers=_auth(bob)).json()["id"]

    assert client.post(f"/v1/claims/{first}/approve", headers=_auth(finder)).status_code == 200
    rejected = client.post(f"/v1/claims/{second}/approve", headers=_auth(finder))
    assert rejected.status_code == 409
    assert rejected.json()["code"] in {"invalid_transition", "already_approved"}


def test_repeated_wrong_codes_trigger_cooldown_and_block_reset(client):
    alice, finder = _token(client, "alice"), _token(client, "finder")
    claim_id = client.post(
        "/v1/claims", json={"item_id": "T-F-9003", "evidence_text": "耳机盒有贴纸"}, headers=_auth(alice)
    ).json()["id"]
    assert client.post(f"/v1/claims/{claim_id}/approve", headers=_auth(finder)).status_code == 200

    for attempt in range(5):
        response = client.post(
            f"/v1/claims/{claim_id}/handover/confirm", json={"code": "00000000"}, headers=_auth(alice)
        )
        assert response.status_code == 422, response.text
        assert f"{4 - attempt}" in response.json()["message"]

    cooling = client.post(
        f"/v1/claims/{claim_id}/handover/confirm", json={"code": "00000000"}, headers=_auth(alice)
    )
    assert cooling.status_code == 429 and cooling.json()["code"] == "cooldown_active"

    reset = client.post(f"/v1/claims/{claim_id}/handover/reset", json={"reason": "改期"}, headers=_auth(alice))
    assert reset.status_code == 409 and reset.json()["code"] == "reset_not_allowed"


def test_withdraw_reject_dispute_and_matching(client):
    alice, bob, finder = _token(client, "alice"), _token(client, "bob"), _token(client, "finder")

    claim_id = client.post(
        "/v1/claims", json={"item_id": "T-F-9004", "evidence_text": "我的杯子"}, headers=_auth(alice)
    ).json()["id"]
    withdrawn = client.post(f"/v1/claims/{claim_id}/withdraw", headers=_auth(alice))
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "WITHDRAWN"
    assert client.post(f"/v1/claims/{claim_id}/withdraw", headers=_auth(alice)).status_code == 409

    first = client.post(
        "/v1/claims", json={"item_id": "T-F-9005", "evidence_text": "尾号 37"}, headers=_auth(alice)
    ).json()["id"]
    rejected = client.post(f"/v1/claims/{first}/reject", json={"reason": "证据不足"}, headers=_auth(finder))
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    assert rejected.json()["reason"] == "证据不足"
    assert client.post(f"/v1/claims/{first}/approve", headers=_auth(finder)).status_code == 409

    second = client.post(
        "/v1/claims", json={"item_id": "T-F-9005", "evidence_text": "卡面有贴纸"}, headers=_auth(bob)
    ).json()["id"]
    assert client.post(f"/v1/claims/{second}/approve", headers=_auth(finder)).status_code == 200
    disputed = client.post(
        f"/v1/claims/{second}/dispute", json={"reason": "交接地点不一致"}, headers=_auth(bob)
    )
    assert disputed.status_code == 200 and disputed.json()["status"] == "DISPUTED"
    assert client.get(f"/v1/claims/{second}/code", headers=_auth(bob)).status_code == 409

    assert client.get(f"/v1/claims/{second}/dispute-export", headers=_auth(bob)).status_code == 200
    assert client.get(f"/v1/claims/{second}/dispute-export", headers=_auth(alice)).status_code == 403

    listed = client.get("/v1/claims", headers=_auth(bob)).json()
    assert listed["page"] == 1 and listed["page_size"] == 20
    assert second in [row["id"] for row in listed["items"]]

    matches = client.get("/v1/matches", params={"item_id": "T-L-9001"}, headers=_auth(alice))
    assert matches.status_code == 200
    body = matches.json()
    assert body["rule_version"] == "rules-v1.1"
    assert body["candidates"], "seeded lost item should match at least one found record"
    for candidate in body["candidates"]:
        assert candidate["score"] >= body["threshold"]
        assert candidate["reasons"]
        assert "publisher_id" not in candidate["item"]

    assert client.get("/v1/matches", params={"item_id": "T-L-9001"}, headers=_auth(bob)).status_code == 403
    assert client.get("/v1/matches", params={"item_id": "T-F-9004"}, headers=_auth(finder)).status_code == 422
