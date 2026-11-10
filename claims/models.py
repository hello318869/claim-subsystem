"""Claim and conversation persistence (C).

Two database-level guards back the contract's concurrency rules (§7.2.7): a post can have at
most one *active* claim per applicant, and at most one *accepted* claim overall.  They are
modelled as nullable unique keys because MySQL has no partial unique index::

    active_key    = "<post_id>:<applicant_id>"   while status is pending/accepted, else NULL
    accepted_key  = "<post_id>"                  while accepted/completed, else NULL

The service layer also locks the post row before touching claims, so the unique keys are the
last line of defence rather than the primary mechanism.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class Claim(models.Model):
    STATUSES = [
        ("pending", "待审核"),
        ("accepted", "已同意待交接"),
        ("rejected", "已拒绝"),
        ("cancelled", "已取消"),
        ("completed", "已完成"),
        ("closed", "已关闭"),
    ]
    CLOSE_REASONS = [
        ("post_withdrawn", "信息已撤回"),
        ("another_claim_accepted", "已选择另一认领申请"),
    ]

    id = models.CharField(primary_key=True, max_length=36)
    post_id = models.CharField(max_length=64)
    applicant_id = models.CharField(max_length=64)
    publisher_id = models.CharField(max_length=64)
    verification_text = models.CharField(max_length=1000)
    status = models.CharField(max_length=16, choices=STATUSES, default="pending")
    decision_note = models.CharField(max_length=500, null=True, blank=True)
    close_reason = models.CharField(max_length=32, choices=CLOSE_REASONS, null=True, blank=True)
    applicant_confirmed_at = models.DateTimeField(null=True, blank=True)
    publisher_confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_by_id = models.CharField(max_length=64, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    # Nullable with a UNIQUE index: MySQL allows many NULLs but never two equal live values.
    active_key = models.CharField(max_length=160, null=True, blank=True, unique=True)
    accepted_key = models.CharField(max_length=64, null=True, blank=True, unique=True)

    class Meta:
        verbose_name = "认领申请"
        verbose_name_plural = "认领申请"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["post_id", "status"], name="ix_claims_post_status"),
            models.Index(fields=["applicant_id", "created_at"], name="ix_claims_applicant"),
            models.Index(fields=["publisher_id", "created_at"], name="ix_claims_publisher"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"claim:{self.id}:{self.status}"


class ClaimMessage(models.Model):
    """One conversation per claim; ids grow in conversation order (contract §3.8/§6.2)."""

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="messages")
    sender_id = models.CharField(max_length=64)
    content = models.CharField(max_length=1000)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "站内消息"
        verbose_name_plural = "站内消息"
        ordering = ["id"]
        indexes = [models.Index(fields=["claim", "id"], name="ix_claim_messages_claim_id")]

    def __str__(self) -> str:  # pragma: no cover
        return f"message:{self.id}"
