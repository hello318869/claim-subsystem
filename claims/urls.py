"""Claim routes (contract §6), mounted under ``/api/v1`` without trailing slashes."""

from __future__ import annotations

from django.urls import path

from claims import views

urlpatterns = [
    path("claims", views.ClaimCreateView.as_view(), name="claim-create"),
    path("claims/<str:claim_id>", views.ClaimDetailView.as_view(), name="claim-detail"),
    path("claims/<str:claim_id>/accept", views.ClaimAcceptView.as_view(), name="claim-accept"),
    path("claims/<str:claim_id>/reject", views.ClaimRejectView.as_view(), name="claim-reject"),
    path("claims/<str:claim_id>/cancel", views.ClaimCancelView.as_view(), name="claim-cancel"),
    path(
        "claims/<str:claim_id>/confirm-handover",
        views.ClaimConfirmHandoverView.as_view(),
        name="claim-confirm-handover",
    ),
    path(
        "claims/<str:claim_id>/messages",
        views.ClaimMessagesView.as_view(),
        name="claim-messages",
    ),
    path("users/me/claims", views.MyClaimsView.as_view(), name="my-claims"),
    path("posts/<str:post_id>/matches", views.PostMatchesView.as_view(), name="post-matches"),
]
