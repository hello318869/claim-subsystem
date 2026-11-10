"""Request serializers for the claim endpoints.

Unknown and read-only fields are rejected with ``400 VALIDATION_ERROR`` per contract §2.1.
Query parameters are validated by the same classes, so a bad enum or an out-of-range number is
never silently ignored.
"""

from __future__ import annotations

from rest_framework import serializers

from claims.services.claims import CLAIM_STATUSES
from common.serializers import PageQuery, StrictSerializer


class CreateClaimBody(StrictSerializer):
    post_id = serializers.CharField(min_length=1, max_length=64, trim_whitespace=False)
    verification_text = serializers.CharField(min_length=10, max_length=1000)


class AcceptClaimBody(StrictSerializer):
    decision_note = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=500
    )


class RejectClaimBody(StrictSerializer):
    decision_note = serializers.CharField(min_length=1, max_length=500)


class EmptyBody(StrictSerializer):
    """Endpoints whose only input is the actor and the path id."""


class SendMessageBody(StrictSerializer):
    content = serializers.CharField(min_length=1, max_length=1000)


class ClaimListQuery(PageQuery):
    role = serializers.ChoiceField(
        choices=("applicant", "publisher"), required=False, default="applicant"
    )
    status = serializers.ChoiceField(
        choices=sorted(CLAIM_STATUSES), required=False, allow_null=True
    )
    post_id = serializers.CharField(
        required=False, allow_null=True, min_length=1, max_length=64, trim_whitespace=False
    )


class MessageListQuery(StrictSerializer):
    after_id = serializers.CharField(
        required=False, allow_null=True, min_length=1, max_length=64, trim_whitespace=False
    )
    limit = serializers.IntegerField(min_value=1, max_value=100, required=False, default=50)


class MatchQuery(StrictSerializer):
    limit = serializers.IntegerField(min_value=1, max_value=20, required=False, default=10)
