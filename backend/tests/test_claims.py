"""Creating and reading claims (§6.1)."""

from __future__ import annotations

import pytest

from claims.models import Claim
from tests.support import PROOF, RIVAL_PROOF, apply_claim

pytestmark = pytest.mark.django_db


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    assert body["data"] is None
    return body


def test_create_claim_returns_the_contract_view(actors, make_post):
    post = make_post()
    response = actors["alice"].post(
        "/claims", {"post_id": post.id, "verification_text": PROOF}
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["code"] == "OK"

    data = body["data"]
    assert data["post_id"] == post.id
    assert data["applicant_id"] == "alice"
    assert data["status"] == "pending"
    assert data["verification_text"] == PROOF
    assert data["decision_note"] is None
    assert data["close_reason"] is None
    assert data["applicant_confirmed_at"] is None
    assert data["publisher_confirmed_at"] is None
    assert data["created_at"].endswith("Z")
    assert data["updated_at"].endswith("Z")
    assert data["applicant"] == {
        "id": "alice",
        "nickname": "小林",
        "is_campus_verified": True,
        "verification_mode": "demo",
    }
    assert data["publisher"] == {
        "id": "finder",
        "nickname": "小陈",
        "is_campus_verified": True,
        "verification_mode": "demo",
    }
    assert data["post"] == {
        "id": post.id,
        "title": post.title,
        "post_type": "found",
        "status": "open",
    }
    # Identity fields come from the token, never from the body.
    assert Claim.objects.get(pk=data["id"]).applicant_id == "alice"


def test_claim_against_a_lost_post_is_allowed(actors, make_post):
    post = make_post(post_type="lost", publisher_id="bob", title="丢失蓝色水杯")
    response = actors["alice"].post(
        "/claims", {"post_id": post.id, "verification_text": RIVAL_PROOF}
    )
    assert response.status_code == 201, response.content
    assert response.json()["data"]["publisher"]["id"] == "bob"


def test_unverified_actor_gets_identity_required(actors, make_post):
    post = make_post()
    body = assert_error(
        actors["outsider"].post("/claims", {"post_id": post.id, "verification_text": PROOF}),
        403,
        "IDENTITY_REQUIRED",
    )
    assert body["errors"] == {}
    assert Claim.objects.count() == 0


def test_publisher_cannot_claim_own_post(actors, make_post):
    post = make_post()
    assert_error(
        actors["finder"].post("/claims", {"post_id": post.id, "verification_text": PROOF}),
        403,
        "FORBIDDEN",
    )


def test_duplicate_active_claim_is_rejected(actors, make_post):
    post = make_post()
    apply_claim(actors, post.id, "alice")
    assert_error(
        actors["alice"].post("/claims", {"post_id": post.id, "verification_text": PROOF}),
        409,
        "DUPLICATE_RESOURCE",
    )
    assert Claim.objects.filter(applicant_id="alice", post_id=post.id).count() == 1


def test_withdrawn_post_is_invisible(actors, make_post):
    post = make_post(status="withdrawn")
    assert_error(
        actors["alice"].post("/claims", {"post_id": post.id, "verification_text": PROOF}),
        404,
        "NOT_FOUND",
    )


def test_unknown_post_is_not_found(actors, reference_data):
    assert_error(
        actors["alice"].post(
            "/claims", {"post_id": "NO-SUCH-POST", "verification_text": PROOF}
        ),
        404,
        "NOT_FOUND",
    )


@pytest.mark.parametrize("status", ("in_handover", "completed"))
def test_public_but_not_open_posts_cannot_be_claimed(actors, make_post, status):
    post = make_post(status=status)
    assert_error(
        actors["alice"].post("/claims", {"post_id": post.id, "verification_text": PROOF}),
        409,
        "STATE_CONFLICT",
    )


def test_unsupported_post_type_is_a_validation_error(actors, make_post):
    post = make_post(post_type="other")
    body = assert_error(
        actors["alice"].post("/claims", {"post_id": post.id, "verification_text": PROOF}),
        400,
        "VALIDATION_ERROR",
    )
    assert "post_id" in body["errors"]


@pytest.mark.parametrize(
    "text",
    (
        "太短了",
        "        ",
        "字" * 1001,
    ),
)
def test_verification_text_length_is_enforced(actors, make_post, text):
    post = make_post()
    body = assert_error(
        actors["alice"].post("/claims", {"post_id": post.id, "verification_text": text}),
        400,
        "VALIDATION_ERROR",
    )
    assert "verification_text" in body["errors"]


def test_history_is_kept_and_reapplication_is_allowed(actors, make_post):
    post = make_post()
    first = apply_claim(actors, post.id, "alice")
    rejected = actors["finder"].post(
        f"/claims/{first}/reject", {"decision_note": "特征不符"}
    )
    assert rejected.status_code == 200

    second = apply_claim(actors, post.id, "alice")
    assert first != second
    assert Claim.objects.filter(post_id=post.id, applicant_id="alice").count() == 2
    assert Claim.objects.get(pk=first).status == "rejected"
    assert Claim.objects.get(pk=second).status == "pending"


def test_participants_can_read_the_claim(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")

    applicant_view = actors["alice"].get(f"/claims/{claim_id}")
    publisher_view = actors["finder"].get(f"/claims/{claim_id}")
    assert applicant_view.status_code == publisher_view.status_code == 200
    assert applicant_view.json()["data"]["id"] == claim_id
    assert publisher_view.json()["data"]["id"] == claim_id


def test_non_participant_gets_404_not_403(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    assert_error(actors["bob"].get(f"/claims/{claim_id}"), 404, "NOT_FOUND")
    assert_error(actors["bob"].get(f"/claims/{claim_id}/messages"), 404, "NOT_FOUND")


def test_verification_text_is_never_exposed_to_outsiders(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    response = actors["bob"].get(f"/claims/{claim_id}")
    assert response.status_code == 404
    assert PROOF not in response.content.decode()


def test_list_claims_by_role_and_filters(actors, make_post):
    mine = make_post()
    received = make_post(publisher_id="bob", title="体育馆拾到钥匙")
    apply_claim(actors, mine.id, "alice")
    apply_claim(actors, received.id, "alice")

    applicant = actors["alice"].get("/users/me/claims", {"role": "applicant"}).json()["data"]
    assert applicant["total"] == 2
    assert {item["post_id"] for item in applicant["items"]} == {mine.id, received.id}

    publisher = actors["alice"].get("/users/me/claims", {"role": "publisher"}).json()["data"]
    assert publisher["total"] == 0

    other_publisher = actors["bob"].get("/users/me/claims", {"role": "publisher"}).json()["data"]
    assert other_publisher["total"] == 1
    assert other_publisher["items"][0]["post_id"] == received.id

    filtered = actors["alice"].get(
        "/users/me/claims", {"role": "applicant", "post_id": received.id}
    ).json()["data"]
    assert filtered["total"] == 1

    empty = actors["alice"].get(
        "/users/me/claims", {"role": "applicant", "status": "completed"}
    ).json()["data"]
    assert empty == {
        "items": [],
        "page": 1,
        "page_size": 20,
        "total": 0,
        "total_pages": 0,
    }


def test_list_defaults_to_applicant_role(actors, make_post):
    post = make_post()
    apply_claim(actors, post.id, "alice")
    default = actors["alice"].get("/users/me/claims").json()["data"]
    assert default["total"] == 1


def test_post_id_cannot_be_used_to_read_foreign_claims(actors, make_post):
    post = make_post()
    apply_claim(actors, post.id, "alice")
    foreign = actors["bob"].get(
        "/users/me/claims", {"role": "applicant", "post_id": post.id}
    ).json()["data"]
    assert foreign["items"] == [] and foreign["total"] == 0
