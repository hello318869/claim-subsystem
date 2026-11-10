"""Transaction and locking behaviour against the isolated MySQL instance (§7.3).

These tests need real row locks and real commits, so they run with ``transaction=True`` on
MySQL only.  A barrier inside the B adapter makes both requests reach the locking read before
either can take the row lock, reproducing the races from the acceptance list (T06, T07, T08).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import IntegrityError, connection, connections
from rest_framework.test import APIClient

from claims.models import Claim
from posts import services as post_service
from posts.models import Post
from tests.support import PROOF, RIVAL_PROOF, apply_claim

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.mysql]


@pytest.fixture(autouse=True)
def require_mysql():
    if connection.vendor != "mysql":
        pytest.skip("行级锁与并发语义需要隔离的 MySQL 实例")


@pytest.fixture
def lock_barrier(monkeypatch):
    """Gate the first locking read of each racing thread on a two-party barrier.

    The gate stays off during sequential setup requests and is switched on by
    ``barrier.enable()`` immediately before the concurrent calls.
    """
    barrier = threading.Barrier(2, timeout=15)
    state = {"enabled": False}
    local = threading.local()
    original = post_service.get_post_for_claim

    def wrapped(post_id, *, lock=False):
        if state["enabled"] and lock and not getattr(local, "reached", False):
            local.reached = True
            barrier.wait()
        return original(post_id, lock=lock)

    monkeypatch.setattr(post_service, "get_post_for_claim", wrapped)

    class Controller:
        @staticmethod
        def enable() -> None:
            state["enabled"] = True

    return Controller()


def call(actor, path: str, payload: dict | None = None):
    """Issue one request in its own thread-owned connection."""
    try:
        client = APIClient()
        return client.post(
            f"/api/v1{path}",
            {} if payload is None else payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {actor}",
        )
    finally:
        connections.close_all()


def race(*requests) -> list:
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        futures = [pool.submit(call, *request) for request in requests]
        return [future.result(timeout=40) for future in futures]


def test_concurrent_duplicate_claims_create_only_one_row(
    actors, tokens, make_post, lock_barrier
):
    post = make_post()
    lock_barrier.enable()
    request = (tokens["alice"], "/claims", {"post_id": post.id, "verification_text": PROOF})
    responses = race(request, request)

    assert sorted(response.status_code for response in responses) == [201, 409], [
        response.content for response in responses
    ]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["code"] == "DUPLICATE_RESOURCE"

    assert Claim.objects.filter(post_id=post.id).count() == 1
    assert Post.objects.get(pk=post.id).status == "open"


def test_concurrent_claims_from_different_users_both_succeed(
    actors, tokens, make_post, lock_barrier
):
    post = make_post()
    lock_barrier.enable()
    responses = race(
        (tokens["alice"], "/claims", {"post_id": post.id, "verification_text": PROOF}),
        (tokens["bob"], "/claims", {"post_id": post.id, "verification_text": RIVAL_PROOF}),
    )
    assert [response.status_code for response in responses] == [201, 201], [
        response.content for response in responses
    ]
    assert sorted(Claim.objects.filter(post_id=post.id).values_list("applicant_id", flat=True)) == [
        "alice",
        "bob",
    ]


def test_concurrent_accepts_select_exactly_one_partner(
    actors, tokens, make_post, lock_barrier
):
    post = make_post()
    alice_claim = apply_claim(actors, post.id, "alice")
    bob_claim = apply_claim(actors, post.id, "bob", RIVAL_PROOF)
    lock_barrier.enable()

    responses = race(
        (tokens["finder"], f"/claims/{alice_claim}/accept", {}),
        (tokens["finder"], f"/claims/{bob_claim}/accept", {}),
    )
    assert sorted(response.status_code for response in responses) == [200, 409], [
        response.content for response in responses
    ]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["code"] == "STATE_CONFLICT"

    winner = next(response.json()["data"] for response in responses if response.status_code == 200)
    loser_id = bob_claim if winner["id"] == alice_claim else alice_claim
    assert winner["status"] == "accepted"
    assert winner["post"]["status"] == "in_handover"

    claim_statuses = {
        claim.id: (claim.status, claim.close_reason)
        for claim in Claim.objects.filter(post_id=post.id)
    }
    assert claim_statuses == {
        winner["id"]: ("accepted", None),
        loser_id: ("closed", "another_claim_accepted"),
    }
    assert Post.objects.get(pk=post.id).status == "in_handover"


def test_concurrent_confirmations_complete_claim_and_post(
    actors, tokens, make_post, lock_barrier
):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    assert actors["finder"].post(f"/claims/{claim_id}/accept").status_code == 200
    lock_barrier.enable()

    responses = race(
        (tokens["alice"], f"/claims/{claim_id}/confirm-handover", {}),
        (tokens["finder"], f"/claims/{claim_id}/confirm-handover", {}),
    )
    assert [response.status_code for response in responses] == [200, 200], [
        response.content for response in responses
    ]
    states = {
        (response.json()["data"]["status"], response.json()["data"]["post"]["status"])
        for response in responses
    }
    assert states == {("accepted", "in_handover"), ("completed", "completed")}

    claim = Claim.objects.get(pk=claim_id)
    stored_post = Post.objects.get(pk=post.id)
    assert claim.status == stored_post.status == "completed"
    assert claim.applicant_confirmed_at is not None
    assert claim.publisher_confirmed_at is not None
    assert claim.completed_at is not None and stored_post.completed_at is not None


def test_adapter_failure_rolls_back_claim_and_post_writes(
    actors, make_post, monkeypatch
):
    post = make_post()
    winner = apply_claim(actors, post.id, "alice")
    loser = apply_claim(actors, post.id, "bob", RIVAL_PROOF)

    original = post_service.set_handover_state
    staged: dict = {}

    def failing(post_id, transition):
        changed = original(post_id, transition)
        staged["post_status"] = changed.status
        staged["claim_statuses"] = set(
            Claim.objects.filter(post_id=post_id).values_list("status", flat=True)
        )
        raise RuntimeError("注入的 B 模块故障")

    monkeypatch.setattr(post_service, "set_handover_state", failing)

    response = actors["finder"].post(
        f"/claims/{winner}/accept", {"decision_note": "合成回滚场景"}
    )
    assert response.status_code == 500, response.content
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert staged == {"post_status": "in_handover", "claim_statuses": {"accepted", "closed"}}

    assert Post.objects.get(pk=post.id).status == "open"
    assert {
        claim.id: (claim.status, claim.close_reason, claim.decision_note)
        for claim in Claim.objects.filter(post_id=post.id)
    } == {
        winner: ("pending", None, None),
        loser: ("pending", None, None),
    }

    monkeypatch.setattr(post_service, "set_handover_state", original)
    retry = actors["finder"].post(f"/claims/{winner}/accept")
    assert retry.status_code == 200, retry.content
    assert retry.json()["data"]["status"] == "accepted"


def test_database_unique_key_blocks_a_second_accepted_claim(actors, make_post):
    post = make_post()
    first = apply_claim(actors, post.id, "alice")
    assert actors["finder"].post(f"/claims/{first}/accept").status_code == 200

    with pytest.raises(IntegrityError):
        Claim.objects.create(
            id="second-accepted",
            post_id=post.id,
            applicant_id="bob",
            publisher_id="finder",
            verification_text=PROOF,
            status="accepted",
            accepted_key=post.id,
        )
    assert Claim.objects.get(pk=first).status == "accepted"
