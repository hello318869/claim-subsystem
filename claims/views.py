"""HTTP transport for the claim subsystem (contract §6).

Each write view opens one ``transaction.atomic()`` block that also covers the B adapter calls,
so a claim status change and the matching post status change commit or roll back together
(contract §7.3).
"""

from __future__ import annotations

from django.db import transaction
from rest_framework import status as http_status

from claims import presenters
from claims.serializers import (
    AcceptClaimBody,
    ClaimListQuery,
    CreateClaimBody,
    EmptyBody,
    MatchQuery,
    MessageListQuery,
    RejectClaimBody,
    SendMessageBody,
)
from claims.services import claims as claim_service
from claims.services import matching as match_service
from claims.services import messages as message_service
from common.api import AuthenticatedAPIView
from common.responses import ok, page_payload
from common.serializers import parse_body, parse_query, validate_resource_id


class ClaimCreateView(AuthenticatedAPIView):
    def post(self, request):
        payload = parse_body(CreateClaimBody, request)
        with transaction.atomic():
            claim = claim_service.create_claim(
                request.user, payload["post_id"], payload["verification_text"]
            )
            data = presenters.claim_view(claim, lock=True)
        return ok(data, message="申请成功", status=http_status.HTTP_201_CREATED)


class ClaimDetailView(AuthenticatedAPIView):
    def get(self, request, claim_id: str):
        validate_resource_id(claim_id, "claim_id")
        claim = claim_service.get_claim(request.user, claim_id)
        return ok(presenters.claim_view(claim))


class MyClaimsView(AuthenticatedAPIView):
    def get(self, request):
        filters = parse_query(ClaimListQuery, request)
        records, total = claim_service.list_claims(
            request.user,
            role=filters["role"],
            status=filters.get("status"),
            post_id=filters.get("post_id"),
            page=filters["page"],
            page_size=filters["page_size"],
        )
        return ok(
            page_payload(
                presenters.claim_views(records),
                total,
                filters["page"],
                filters["page_size"],
            ),
            message="查询成功",
        )


class ClaimAcceptView(AuthenticatedAPIView):
    def post(self, request, claim_id: str):
        validate_resource_id(claim_id, "claim_id")
        payload = parse_body(AcceptClaimBody, request, optional=True)
        with transaction.atomic():
            claim = claim_service.accept_claim(
                request.user, claim_id, payload.get("decision_note")
            )
            data = presenters.claim_view(claim, lock=True)
        return ok(data, message="已同意认领")


class ClaimRejectView(AuthenticatedAPIView):
    def post(self, request, claim_id: str):
        validate_resource_id(claim_id, "claim_id")
        payload = parse_body(RejectClaimBody, request)
        with transaction.atomic():
            claim = claim_service.reject_claim(
                request.user, claim_id, payload["decision_note"]
            )
            data = presenters.claim_view(claim, lock=True)
        return ok(data, message="已拒绝认领")


class ClaimCancelView(AuthenticatedAPIView):
    def post(self, request, claim_id: str):
        validate_resource_id(claim_id, "claim_id")
        parse_body(EmptyBody, request, optional=True)
        with transaction.atomic():
            claim = claim_service.cancel_claim(request.user, claim_id)
            data = presenters.claim_view(claim, lock=True)
        return ok(data, message="已取消认领")


class ClaimConfirmHandoverView(AuthenticatedAPIView):
    def post(self, request, claim_id: str):
        validate_resource_id(claim_id, "claim_id")
        parse_body(EmptyBody, request, optional=True)
        with transaction.atomic():
            claim = claim_service.confirm_handover(request.user, claim_id)
            data = presenters.claim_view(claim, lock=True)
        return ok(data, message="已确认交接")


class ClaimMessagesView(AuthenticatedAPIView):
    def get(self, request, claim_id: str):
        validate_resource_id(claim_id, "claim_id")
        filters = parse_query(MessageListQuery, request)
        records, next_after_id, has_more = message_service.list_messages(
            request.user, claim_id, filters.get("after_id"), filters["limit"]
        )
        return ok(
            {
                "items": presenters.message_views(records),
                "next_after_id": next_after_id,
                "has_more": has_more,
            },
            message="查询成功",
        )

    def post(self, request, claim_id: str):
        validate_resource_id(claim_id, "claim_id")
        payload = parse_body(SendMessageBody, request)
        with transaction.atomic():
            message = message_service.send_message(
                request.user, claim_id, payload["content"]
            )
            data = presenters.message_view(message)
        return ok(data, message="发送成功", status=http_status.HTTP_201_CREATED)


class PostMatchesView(AuthenticatedAPIView):
    def get(self, request, post_id: str):
        validate_resource_id(post_id, "post_id")
        filters = parse_query(MatchQuery, request)
        return ok(
            match_service.find_matches(request.user, post_id, filters["limit"]),
            message="查询成功",
        )


__all__ = [
    "ClaimAcceptView",
    "ClaimCancelView",
    "ClaimConfirmHandoverView",
    "ClaimCreateView",
    "ClaimDetailView",
    "ClaimMessagesView",
    "ClaimRejectView",
    "MyClaimsView",
    "PostMatchesView",
]
