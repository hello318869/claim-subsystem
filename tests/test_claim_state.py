"""Claim state machine: accept, reject, cancel and two-party confirmation (§6.1, §7.1)."""

from __future__ import annotations

import pytest
from django.db import transaction

from claims.models import Claim
from claims.services.claims import close_pending_claims, has_completed_claim
from posts.models import Post
from tests.support import PROOF, RIVAL_PROOF, accept_claim, apply_claim

pytestmark = pytest.mark.django_db


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    return body


def test_accept_reserves_the_post_and_closes_competing_claims(actors, make_post):
    post = make_post()
    winner = apply_claim(actors, post.id, "alice")
    loser = apply_claim(actors, post.id, "bob", RIVAL_PROOF)

    response = accept_claim(actors, winner, "finder", "特征相符")
    assert response.status_code == 200, response.content
    data = response.json()["data"]
    assert data["status"] == "accepted"
    assert data["decision_note"] == "特征相符"
    assert data["post"]["status"] == "in_handover"

    closed = actors["bob"].get(f"/claims/{loser}").json()["data"]
    assert closed["status"] == "closed"
    assert closed["close_reason"] == "another_claim_accepted"
    assert Post.objects.get(pk=post.id).status == "in_handover"


def test_only_the_publisher_can_accept(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    assert_error(accept_claim(actors, claim_id, "alice"), 403, "FORBIDDEN")
    assert_error(accept_claim(actors, claim_id, "bob"), 404, "NOT_FOUND")
    assert Claim.objects.get(pk=claim_id).status == "pending"


def test_accept_is_idempotent_and_keeps_the_first_note(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    accept_claim(actors, claim_id, "finder", "第一次说明")

    again = accept_claim(actors, claim_id, "finder", "第二次说明")
    assert again.status_code == 200
    assert again.json()["data"]["status"] == "accepted"
    assert again.json()["data"]["decision_note"] == "第一次说明"


def test_second_accept_after_selection_conflicts(actors, make_post):
    post = make_post()
    first = apply_claim(actors, post.id, "alice")
    second = apply_claim(actors, post.id, "bob", RIVAL_PROOF)
    accept_claim(actors, first, "finder")

    # The competing claim was closed by the accepted one.
    assert_error(accept_claim(actors, second, "finder"), 409, "STATE_CONFLICT")


def test_accept_requires_the_post_to_still_be_open(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    Post.objects.filter(pk=post.id).update(status="completed")
    assert_error(accept_claim(actors, claim_id, "finder"), 409, "STATE_CONFLICT")


def test_reject_requires_a_note_and_keeps_the_post_open(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")

    assert_error(actors["finder"].post(f"/claims/{claim_id}/reject", {}), 400, "VALIDATION_ERROR")
    assert_error(
        actors["finder"].post(f"/claims/{claim_id}/reject", {"decision_note": "   "}),
        400,
        "VALIDATION_ERROR",
    )

    response = actors["finder"].post(
        f"/claims/{claim_id}/reject", {"decision_note": "特征不符"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "rejected"
    assert response.json()["data"]["post"]["status"] == "open"
    assert Post.objects.get(pk=post.id).status == "open"


def test_reject_is_idempotent_for_the_publisher(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    actors["finder"].post(f"/claims/{claim_id}/reject", {"decision_note": "第一次"})
    again = actors["finder"].post(f"/claims/{claim_id}/reject", {"decision_note": "第二次"})
    assert again.status_code == 200
    assert again.json()["data"]["decision_note"] == "第一次"


def test_only_the_applicant_cancels_a_pending_claim(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")

    assert_error(actors["finder"].post(f"/claims/{claim_id}/cancel"), 403, "FORBIDDEN")
    cancelled = actors["alice"].post(f"/claims/{claim_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert Post.objects.get(pk=post.id).status == "open"


def test_repeat_cancel_requires_the_original_actor(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    actors["alice"].post(f"/claims/{claim_id}/cancel")

    again = actors["alice"].post(f"/claims/{claim_id}/cancel")
    assert again.status_code == 200
    assert_error(actors["finder"].post(f"/claims/{claim_id}/cancel"), 403, "FORBIDDEN")


def test_cancel_after_acceptance_reopens_the_post(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    accept_claim(actors, claim_id, "finder")

    response = actors["finder"].post(f"/claims/{claim_id}/cancel")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"
    assert Post.objects.get(pk=post.id).status == "open"

    # History is not restored: a different applicant can now be accepted.
    other = apply_claim(actors, post.id, "bob", RIVAL_PROOF)
    assert accept_claim(actors, other, "finder").status_code == 200


def test_cannot_cancel_after_one_party_confirmed(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    accept_claim(actors, claim_id, "finder")
    assert actors["alice"].post(f"/claims/{claim_id}/confirm-handover").status_code == 200

    assert_error(actors["alice"].post(f"/claims/{claim_id}/cancel"), 409, "STATE_CONFLICT")
    assert_error(actors["finder"].post(f"/claims/{claim_id}/cancel"), 409, "STATE_CONFLICT")


def test_confirm_requires_an_accepted_claim(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    assert_error(
        actors["alice"].post(f"/claims/{claim_id}/confirm-handover"), 409, "STATE_CONFLICT"
    )


def test_two_party_confirmation_completes_claim_and_post(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    accept_claim(actors, claim_id, "finder")

    first = actors["alice"].post(f"/claims/{claim_id}/confirm-handover").json()["data"]
    assert first["status"] == "accepted"
    assert first["applicant_confirmed_at"].endswith("Z")
    assert first["publisher_confirmed_at"] is None
    assert first["post"]["status"] == "in_handover"
    assert Post.objects.get(pk=post.id).status == "in_handover"

    second = actors["finder"].post(f"/claims/{claim_id}/confirm-handover").json()["data"]
    assert second["status"] == "completed"
    assert second["applicant_confirmed_at"] == first["applicant_confirmed_at"]
    assert second["publisher_confirmed_at"] is not None
    assert second["post"]["status"] == "completed"

    stored_post = Post.objects.get(pk=post.id)
    assert stored_post.status == "completed"
    assert stored_post.completed_at is not None
    stored_claim = Claim.objects.get(pk=claim_id)
    assert stored_claim.completed_at is not None
    assert stored_claim.active_key is None


def test_repeated_confirmation_does_not_overwrite_timestamps(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    accept_claim(actors, claim_id, "finder")
    first = actors["alice"].post(f"/claims/{claim_id}/confirm-handover").json()["data"]
    actors["finder"].post(f"/claims/{claim_id}/confirm-handover")

    repeated_applicant = actors["alice"].post(f"/claims/{claim_id}/confirm-handover")
    assert repeated_applicant.status_code == 200
    assert repeated_applicant.json()["data"]["applicant_confirmed_at"] == first["applicant_confirmed_at"]
    assert repeated_applicant.json()["data"]["status"] == "completed"


def test_outsider_cannot_confirm(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    accept_claim(actors, claim_id, "finder")
    assert_error(
        actors["bob"].post(f"/claims/{claim_id}/confirm-handover"), 404, "NOT_FOUND"
    )


def test_withdrawing_a_post_closes_pending_claims(actors, make_post):
    post = make_post()
    first = apply_claim(actors, post.id, "alice")
    second = apply_claim(actors, post.id, "bob", RIVAL_PROOF)

    # Stand-in for B's withdraw flow (contract §7.3): lock the post, withdraw, close claims.
    with transaction.atomic():
        row = Post.objects.select_for_update().get(pk=post.id)
        row.status = "withdrawn"
        row.save(update_fields=["status", "updated_at"])
        assert close_pending_claims(post.id, "post_withdrawn") == 2

    for claim_id in (first, second):
        record = Claim.objects.get(pk=claim_id)
        assert record.status == "closed"
        assert record.close_reason == "post_withdrawn"
        assert record.active_key is None


def test_close_pending_claims_can_spare_one_claim(actors, make_post):
    post = make_post()
    keep = apply_claim(actors, post.id, "alice")
    drop = apply_claim(actors, post.id, "bob", RIVAL_PROOF)

    with transaction.atomic():
        assert close_pending_claims(post.id, "another_claim_accepted", keep) == 1

    assert Claim.objects.get(pk=keep).status == "pending"
    assert Claim.objects.get(pk=drop).status == "closed"


def test_close_pending_claims_validates_reason(actors, make_post):
    post = make_post()
    from common.errors import AppError

    with pytest.raises(AppError) as caught:
        close_pending_claims(post.id, "made_up")
    assert caught.value.status_code == 400


def test_has_completed_claim_tracks_completion(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    accept_claim(actors, claim_id, "finder")

    with transaction.atomic():
        assert has_completed_claim(post.id) is False
    actors["alice"].post(f"/claims/{claim_id}/confirm-handover")
    actors["finder"].post(f"/claims/{claim_id}/confirm-handover")
    with transaction.atomic():
        assert has_completed_claim(post.id) is True


def test_database_unique_key_blocks_duplicate_active_claims(actors, make_post):
    from django.db import IntegrityError

    post = make_post()
    apply_claim(actors, post.id, "alice")
    with pytest.raises(IntegrityError):
        Claim.objects.create(
            id="duplicate-active",
            post_id=post.id,
            applicant_id="alice",
            publisher_id="finder",
            verification_text=PROOF,
            status="pending",
            active_key=f"{post.id}:alice",
        )
