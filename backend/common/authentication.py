"""Bearer token authentication against the identity adapter (contract §2.2).

A missing header means "anonymous" (public endpoints still work).  A malformed, unknown,
expired or revoked token is ``401 UNAUTHENTICATED`` even on public endpoints, so the client can
discard the token and retry anonymously.
"""

from __future__ import annotations

from rest_framework import authentication

from common.errors import AppError
from identity import services as identity_services


class BearerAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION") or ""
        if not header:
            return None
        scheme, _, token = header.partition(" ")
        if scheme.lower() != self.keyword.lower() or not token or any(char.isspace() for char in token):
            raise AppError(
                401,
                "UNAUTHENTICATED",
                "登录凭证无效",
                headers={"WWW-Authenticate": "Bearer"},
            )
        actor = identity_services.require_user(token)
        return (actor, token)

    def authenticate_header(self, request) -> str:
        return self.keyword
