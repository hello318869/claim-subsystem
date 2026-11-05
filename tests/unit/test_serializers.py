from __future__ import annotations

from datetime import datetime, timezone

from app import serializers
from app.models import Claim, ListingSnapshot, Message


def _listing() -> ListingSnapshot:
    return ListingSnapshot(
        item_id="F-1",
        kind="found",
        title="黑色双肩包",
        category="bag",
        occurred_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
        location="图书馆二楼",
        description="黑色双肩包",
        status="published",
        publisher_user_id="finder",
        origin="demo",
        synced_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )


def test_public_listing_has_no_publisher_id():
    dto = serializers.public_listing(_listing())
    assert "publisher_id" not in dto and "publisher_user_id" not in dto
    assert dto["id"] == "F-1"
    assert dto["claimable"] is True
    assert dto["occurred_at"].endswith("Z")


def test_public_listing_claimed_is_not_claimable():
    dto = serializers.public_listing(_listing(), approved=True)
    assert dto["status"] == "claimed"
    assert dto["claimable"] is False


def test_claim_dto_shape_and_roles():
    claim = Claim(
        id="11111111-2222-3333-4444-555555555555",
        item_id="F-1",
        applicant_id="alice",
        finder_id="finder",
        status="PENDING",
        evidence_text="包内有蓝色水杯",
        item_number="ASSET-1",
        created_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
        updated_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )
    applicant_view = serializers.claim_dto(claim, "alice")
    finder_view = serializers.claim_dto(claim, "finder")
    assert applicant_view["my_role"] == "applicant"
    assert finder_view["my_role"] == "finder"
    assert applicant_view["confirmed_by_me"] is False
    assert "applicant_id" not in applicant_view and "finder_id" not in applicant_view


def test_message_dto_has_no_sender_id():
    claim = Claim(
        id="11111111-2222-3333-4444-555555555555",
        item_id="F-1",
        applicant_id="alice",
        finder_id="finder",
        status="PENDING",
        evidence_text="x",
        created_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
        updated_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )
    message = Message(
        id="m-1",
        claim_id=claim.id,
        sender_role="applicant",
        body="你好",
        created_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )
    mine = serializers.message_dto(message, claim, "alice")
    theirs = serializers.message_dto(message, claim, "finder")
    assert set(mine) == {"id", "text", "sender_alias", "is_mine", "created_at"}
    assert mine["is_mine"] is True and theirs["is_mine"] is False
    assert "sender_id" not in mine


def test_aliases_are_derived_not_identity():
    alias = serializers.alias_for("abcdef12-0000", "applicant")
    assert alias.startswith("申请人-")
    assert "alice" not in alias
