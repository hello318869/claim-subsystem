"""B invokes C in the transaction that already holds the Post row lock."""

from claims.services.claims import close_pending_claims, has_completed_claim


__all__ = ["close_pending_claims", "has_completed_claim"]
