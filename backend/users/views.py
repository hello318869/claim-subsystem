from rest_framework.views import APIView

from common.clock import iso
from common.contracts import UserSummary
from common.responses import ok, page_payload
from common.serializers import parse_body, parse_query

from . import serializers as s
from .authentication import BearerAuthentication
from .permissions import LoginRequired, PublicAccess
from .selectors import current_user, get_campus_binding, my_posts
from .services import bind_campus, issue_session, login_user, register_user, revoke_session, update_profile, user_summary
from .throttles import enforce_binding_rate_limit, enforce_login_rate_limit


class UserAPIView(APIView):
    """A's ORM user and revocable session are available as request.user and request.auth."""

    authentication_classes = [BearerAuthentication]


class RegisterView(UserAPIView):
    permission_classes = [PublicAccess]

    def post(self, request):
        data = parse_body(s.RegisterInput, request)
        return ok(s.user_self(register_user(**data)), status=201)


class LoginView(UserAPIView):
    permission_classes = [PublicAccess]

    def post(self, request):
        enforce_login_rate_limit(request)
        data = parse_body(s.LoginInput, request)
        user = login_user(data["username"], data["password"])
        token, session = issue_session(user)
        return ok({"access_token": token, "token_type": "Bearer",
                   "expires_at": iso(session.expires_at), "user": s.user_self(user)})


class LogoutView(UserAPIView):
    permission_classes = [LoginRequired]

    def post(self, request):
        parse_body(s.EmptyInput, request)
        revoke_session(request.auth)
        return ok()


class MeView(UserAPIView):
    permission_classes = [LoginRequired]

    def get(self, request):
        return ok(s.user_self(current_user(request.user)))

    def patch(self, request):
        data = parse_body(s.UpdateProfileInput, request)
        return ok(s.user_self(update_profile(current_user(request.user), data)))


class CampusBindingView(UserAPIView):
    permission_classes = [LoginRequired]

    def get(self, request):
        binding = get_campus_binding(request.user)
        return ok(s.binding_view(binding) if binding else None)

    def post(self, request):
        enforce_binding_rate_limit(request)
        data = parse_body(s.CampusBindingInput, request)
        return ok(s.binding_view(bind_campus(request.user, **data)), status=201)


class MyPostsView(UserAPIView):
    """我的发布（契约 v0.3）：A 直接查询 B 的 Post 表，默认包含本人全部状态。"""
    permission_classes = [LoginRequired]

    def get(self, request):
        from posts.presenters import post_summary

        query = parse_query(s.MyPostsQuery, request)
        page, size = query["page"], query["page_size"]
        queryset = my_posts(request.user, query)
        total = queryset.count()
        offset = (page - 1) * size
        publisher = UserSummary(**user_summary(request.user))
        publishers = {publisher.id: publisher}
        rows = queryset[offset:offset + size] if offset < total else []
        items = [post_summary(row, publishers=publishers) for row in rows]
        return ok(page_payload(items, total, page, size))
