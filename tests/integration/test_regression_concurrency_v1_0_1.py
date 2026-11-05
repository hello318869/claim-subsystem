"""V1.0.1 regression: concurrent create/approve/withdraw/reject races.

These tests are intentionally strict: they describe the post-fix contract.
They are additions; the historical xfail/failed v1.0 tests remain untouched.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from claimtest.api import (
    Api,
    Paths,
    claim_status,
    entity_id,
    expect_status,
    unwrap_entity,
)


def _claim_body(scenario, actor: str = "alice") -> dict:
    return scenario.claimant(actor).create_payload(
        "V1.0.1 并发回归：盒盖内侧有星星贴纸，私有编号见 item_number。"
    )


def _create_with_key(base_url: str, scenario, key: str, barrier: threading.Barrier):
    client = Api(base_url)
    try:
        client.login("alice")
        barrier.wait(timeout=15)
        return client.post(
            Paths.CLAIMS,
            actor="alice",
            json=_claim_body(scenario),
            idempotency_key=key,
        )
    finally:
        client.close()


def _create_claim(api: Api, scenario, actor: str = "alice") -> object:
    return entity_id(unwrap_entity(api.create_claim(scenario, actor)))


def _approve_in_thread(base_url: str, claim_id: object, barrier: threading.Barrier):
    client = Api(base_url)
    try:
        client.login("finder")
        barrier.wait(timeout=15)
        return client.approve(claim_id, "finder")
    finally:
        client.close()


def _withdraw_in_thread(
    base_url: str, claim_id: object, actor: str, barrier: threading.Barrier
):
    client = Api(base_url)
    try:
        client.login(actor)
        barrier.wait(timeout=15)
        return client.withdraw(claim_id, actor)
    finally:
        client.close()


def _reject_in_thread(base_url: str, claim_id: object, barrier: threading.Barrier):
    client = Api(base_url)
    try:
        client.login("finder")
        barrier.wait(timeout=15)
        return client.reject(claim_id, "finder", "并发回归：证据不足")
    finally:
        client.close()


def _run_pair(first, second):
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(first, barrier), pool.submit(second, barrier)]
        return [future.result(timeout=30) for future in futures]


def test_same_actor_different_keys_concurrent_create_yields_one_pending(
    api: Api, base_url: str, scenario, db_tools
):
    first_key = f"reg-create-a-{uuid.uuid4().hex}"
    second_key = f"reg-create-b-{uuid.uuid4().hex}"
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_create_with_key, base_url, scenario, first_key, barrier),
            pool.submit(_create_with_key, base_url, scenario, second_key, barrier),
        ]
        responses = [future.result(timeout=30) for future in futures]

    for response in responses:
        expect_status(response, (200, 201))
    ids = {str(entity_id(unwrap_entity(response))) for response in responses}
    assert len(ids) == 1, f"different keys for one actor created multiple claims: {ids}"
    assert db_tools.count_pending_claims(scenario.found_id, "alice") == 1
    assert db_tools.count_claims_for_item(scenario.found_id) == 1

    detail = unwrap_entity(api.get_claim(next(iter(ids)), "alice"))
    assert detail["status"] == "PENDING"


def test_approve_and_withdraw_cross_concurrency_keeps_one_terminal(
    api: Api, base_url: str, scenario, db_tools
):
    claim_id = _create_claim(api, scenario)
    responses = _run_pair(
        lambda barrier: _approve_in_thread(base_url, claim_id, barrier),
        lambda barrier: _withdraw_in_thread(base_url, claim_id, "alice", barrier),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]

    status = db_tools.get_claim_status(claim_id)
    assert status in {"APPROVED", "WITHDRAWN"}
    assert claim_status(api, claim_id, "alice") == status
    if status == "APPROVED":
        assert db_tools.count_approvals(scenario.found_id) == 1
    else:
        assert db_tools.count_approvals(scenario.found_id) == 0


def test_approve_and_reject_cross_concurrency_keeps_one_terminal(
    api: Api, base_url: str, scenario, db_tools
):
    claim_id = _create_claim(api, scenario)
    responses = _run_pair(
        lambda barrier: _approve_in_thread(base_url, claim_id, barrier),
        lambda barrier: _reject_in_thread(base_url, claim_id, barrier),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]

    status = db_tools.get_claim_status(claim_id)
    assert status in {"APPROVED", "REJECTED"}
    assert claim_status(api, claim_id, "alice") == status
    if status == "APPROVED":
        assert db_tools.count_approvals(scenario.found_id) == 1
    else:
        assert db_tools.count_approvals(scenario.found_id) == 0
