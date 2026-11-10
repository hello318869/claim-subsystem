"""Small DRF view base classes shared by the apps."""

from __future__ import annotations

from django.conf import settings
from rest_framework.views import APIView

from common.authentication import BearerAuthentication
from common.errors import AppError


class AuthenticatedAPIView(APIView):
    """Require a valid bearer token and expose the actor as ``request.user``."""

    authentication_classes = [BearerAuthentication]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.user is None:
            raise AppError(
                401,
                "UNAUTHENTICATED",
                "请先登录",
                headers={"WWW-Authenticate": "Bearer"},
            )


class OptionalAuthAPIView(APIView):
    """Resolve a token when supplied; anonymous access stays allowed."""

    authentication_classes = [BearerAuthentication]


def require_demo_mode() -> None:
    if not settings.DEMO_MODE:
        raise AppError(404, "NOT_FOUND", "演示接口未开启")
