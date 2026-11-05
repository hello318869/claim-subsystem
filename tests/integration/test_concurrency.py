"""Concurrency: two approvals on one found listing, and same-key claim replay."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from claimtest.api import (
    Api,
    Paths,
    assert_error,
    claim_status,
    entity_id,
    expect_status,
    json_object,
    unwrap_entity,
)


def _approve_with_own_client(base_url: str, claim_id: object, barrier: threading.Barrier):
    client = Api(base_url)
    try:
        client.login("finder")
        barrier.wait(timeout=15)
        return client.approve(claim_id, "finder")
    finally:
        client.close()


def _create_claim_with_key(
    base_url: str, scenario, key: str, barrier: threading.Barrier
):
    client = Api(base_url)
    try:
        client.login("alice")
        spec = scenario.claimant("alice")
        body = spec.create_payload("并发幂等测试：盒盖内侧有星星贴纸。")
        barrier.wait(timeout=15)
        return client.post(
            Paths.CLAIMS, actor="alice", json=body, idempotency_key=key
        )
    finally:
        client.close()


def test_two_concurrent_approvals_only_one_succeeds(api: Api, base_url: str, world):
    for _round in range(3):
        scenario = world.take_scenario()
        alice_claim = entity_id(unwrap_entity(api.create_claim(scenario, "alice")))
        bob_claim = entity_id(unwrap_entity(api.create_claim(scenario, "bob")))
        assert claim_status(api, alice_claim, "alice") == "PENDING"
        assert claim_status(api, bob_claim, "bob") == "PENDING"

        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_approve_with_own_client, base_url, alice_claim, barrier),
                pool.submit(_approve_with_own_client, base_url, bob_claim, barrier),
            ]
            responses = [future.result(timeout=30) for future in futures]

        statuses = sorted(response.status_code for response in responses)
        assert statuses == [200, 409], [
            (response.status_code, response.text[:200]) for response in responses
        ]
        loser = next(response for response in responses if response.status_code == 409)
        assert_error(loser, 409)

        alice_status = claim_status(api, alice_claim, "alice")
        bob_status = claim_status(api, bob_claim, "bob")
        assert {alice_status, bob_status} == {"APPROVED", "CLOSED_OTHER"}


def test_concurrent_same_key_claim_replay(base_url: str, world):
    scenario = world.take_scenario()
    key = f"concurrent-claim-{uuid.uuid4().hex}"
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_create_claim_with_key, base_url, scenario, key, barrier),
            pool.submit(_create_claim_with_key, base_url, scenario, key, barrier),
        ]
        responses = [future.result(timeout=30) for future in futures]

    for response in responses:
        expect_status(response, (200, 201))
    ids = {str(entity_id(unwrap_entity(response))) for response in responses}
    assert len(ids) == 1, f"same key created multiple claims: {ids}"
