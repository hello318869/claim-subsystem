"""Demo session endpoints (local A adapter).

Real ``/auth/login`` etc. belong to member A.  These endpoints only exist while ``DEMO_MODE``
is on and are used by ``web/team.html`` for integration testing.
"""

from __future__ import annotations

from rest_framework import serializers
from rest_framework.views import APIView

from common.api import AuthenticatedAPIView, require_demo_mode
from common.errors import AppError
from common.responses import ok
from common.serializers import StrictSerializer, parse_body
from identity import services


class DemoLoginBody(StrictSerializer):
    actor = serializers.CharField(min_length=1, max_length=64)


class DemoTokenView(APIView):
    def initial(self, request, *args, **kwargs):
        require_demo_mode()
        super().initial(request, *args, **kwargs)

    def post(self, request):
        payload = parse_body(DemoLoginBody, request)
        return ok(services.issue_token(payload["actor"]), message="登录成功")


class DemoLogoutView(AuthenticatedAPIView):
    def initial(self, request, *args, **kwargs):
        require_demo_mode()
        super().initial(request, *args, **kwargs)

    def post(self, request):
        token = request.auth
        if not isinstance(token, str):  # pragma: no cover - defensive contract check
            raise AppError(401, "UNAUTHENTICATED", "请先登录")
        services.logout(token)
        return ok(None, message="已退出登录")
