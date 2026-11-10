"""FR-A-01/02/03/08/10：注册、登录、登出、Bearer 认证与登录限流。"""
from django.conf import settings
from django.test import override_settings

from users.models import AuthSession, User

from . import UserApiTestCase

USER_SELF_FIELDS = {"id", "username", "nickname", "bio", "is_campus_verified",
                    "verification_mode", "created_at", "updated_at"}


class RegisterTests(UserApiTestCase):
    """FR-A-01 账号注册。"""

    def register(self, **overrides):
        payload = {"username": "new_student", "password": "new-password-123", "nickname": "新同学"}
        payload.update(overrides)
        return self.client.post("/api/v1/auth/register", payload, format="json")

    def test_register_success_returns_user_self_without_token_fr_a01(self):
        response = self.register()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["code"], "OK")
        data = response.data["data"]
        self.assertEqual(set(data), USER_SELF_FIELDS)
        self.assertEqual(data["username"], "new_student")
        self.assertEqual(data["nickname"], "新同学")
        self.assertIsInstance(data["id"], str)
        self.assertEqual(data["is_campus_verified"], False)
        self.assertIsNone(data["verification_mode"])
        self.assertTrue(data["created_at"].endswith("Z"))
        self.assertTrue(data["updated_at"].endswith("Z"))
        self.assertNotIn("access_token", data)
        self.assertEqual(AuthSession.objects.count(), 0)

    def test_register_stores_lowercase_username_and_password_hash_fr_a01(self):
        response = self.register(username="Mixed_CaseUser")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["username"], "mixed_caseuser")
        user = User.objects.get(username="mixed_caseuser")
        self.assertNotEqual(user.password, "new-password-123")
        self.assertTrue(user.check_password("new-password-123"))
        self.assertNotIn("new-password-123", user.password)

    def test_register_trims_text_but_not_password_fr_a01(self):
        response = self.register(username="  trim_user  ", nickname="  昵称  ", password="  spaced-pass  ")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["username"], "trim_user")
        self.assertEqual(response.data["data"]["nickname"], "昵称")
        # 密码不裁剪：带首尾空格的原文才能登录，裁剪后的版本应失败。
        login = self.client.post("/api/v1/auth/login", {"username": "trim_user", "password": "  spaced-pass  "}, format="json")
        self.assertEqual(login.status_code, 200, login.data)
        self.username_trimmed_login = self.client.post(
            "/api/v1/auth/login", {"username": "trim_user", "password": "spaced-pass"}, format="json")
        self.assertEqual(self.username_trimmed_login.status_code, 401)

    def test_register_duplicate_returns_409_fr_a01(self):
        self.assertEqual(self.register(username="Twin_User").status_code, 201)
        response = self.register(username="twin_user")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "DUPLICATE_RESOURCE")
        self.assertIsNone(response.data["data"])
        self.assertEqual(User.objects.filter(username="twin_user").count(), 1)

    def test_register_invalid_username_returns_400_fr_a01(self):
        for username in ("abc", "bad-name", "名字名字", "a" * 33):
            with self.subTest(username=username):
                response = self.register(username=username)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                self.assertIn("username", response.data["errors"])

    def test_register_invalid_password_and_nickname_returns_400_fr_a01(self):
        for field, payload in (
            ("password", {"password": "short7"}),
            ("password", {"password": "x" * 65}),
            ("nickname", {"nickname": ""}),
            ("nickname", {"nickname": "名" * 31}),
        ):
            with self.subTest(field=field, payload=payload):
                response = self.register(**payload)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn(field, response.data["errors"])

    def test_register_unknown_or_readonly_field_returns_400_fr_a01(self):
        for payload in ({"is_campus_verified": True}, {"bio": "自我介绍"}, {"password_hash": "x"}):
            with self.subTest(payload=payload):
                response = self.register(**payload)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                self.assertTrue(response.data["errors"])


class LoginTests(UserApiTestCase):
    """FR-A-02 登录。"""

    def setUp(self):
        super().setUp()
        self.user = self.make_user(username="login_user", password="login-pass-123", nickname="登录用户")

    def login(self, **overrides):
        payload = {"username": "login_user", "password": "login-pass-123"}
        payload.update(overrides)
        return self.client.post("/api/v1/auth/login", payload, format="json")

    def test_login_success_returns_token_and_user_fr_a02(self):
        response = self.login(username="LOGIN_USER")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["token_type"], "Bearer")
        self.assertIsInstance(data["access_token"], str)
        self.assertGreaterEqual(len(data["access_token"]), 32)
        self.assertTrue(data["expires_at"].endswith("Z"))
        self.assertEqual(set(data["user"]), USER_SELF_FIELDS)
        self.assertEqual(data["user"]["id"], str(self.user.pk))
        self.assertEqual(data["user"]["username"], "login_user")
        self.assertNotIn("password", data["user"])
        self.assertNotIn("hash", str(data["user"]).lower())

    def test_login_stores_only_token_digest_fr_a02(self):
        token = self.login().data["data"]["access_token"]
        session = AuthSession.objects.get(user=self.user)
        self.assertNotEqual(session.token_digest, token)
        self.assertFalse(AuthSession.objects.filter(token_digest=token).exists())

    def test_login_wrong_password_returns_uniform_401_fr_a02(self):
        response = self.login(password="wrong-password")
        self.assertEqual(response.status_code, 401, response.data)
        self.assertEqual(response.data["code"], "UNAUTHENTICATED")
        self.assertEqual(response.data["message"], "账号或密码错误")
        self.assertIsNone(response.data["data"])

    def test_login_unknown_or_inactive_account_returns_401_fr_a02(self):
        response = self.login(username="nobody_here")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["message"], "账号或密码错误")
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.login()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["message"], "账号或密码错误")

    def test_two_logins_create_independent_sessions_fr_a02(self):
        first = self.login().data["data"]["access_token"]
        second = self.login().data["data"]["access_token"]
        self.assertNotEqual(first, second)
        self.assertEqual(AuthSession.objects.filter(user=self.user).count(), 2)

    def test_login_rejects_unknown_field_and_repairs_missing_field_fr_a02(self):
        response = self.client.post(
            "/api/v1/auth/login", {"username": "login_user", "password": "login-pass-123", "nickname": "x"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("nickname", response.data["errors"])
        response = self.client.post("/api/v1/auth/login", {"username": "login_user"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("password", response.data["errors"])


class LogoutTests(UserApiTestCase):
    """FR-A-03 退出登录。"""

    def setUp(self):
        super().setUp()
        self.user = self.make_user(username="logout_user", password="logout-pass-123", nickname="退出用户")

    def test_logout_revokes_only_current_session_fr_a03(self):
        first = self.login_token("logout_user", "logout-pass-123")
        second = self.login_token("logout_user", "logout-pass-123")
        self.use_token(first)
        response = self.client.post("/api/v1/auth/logout", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["data"])
        self.use_token(first)
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)
        self.use_token(second)
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 200)
        self.assertEqual(AuthSession.objects.filter(user=self.user).count(), 1)

    def test_logout_without_token_returns_401_fr_a03(self):
        response = self.client.post("/api/v1/auth/logout", {}, format="json")
        self.assertEqual(response.status_code, 401, response.data)
        self.assertEqual(response.data["code"], "UNAUTHENTICATED")


class BearerAuthTests(UserApiTestCase):
    """FR-A-08 登录身份校验。"""

    def setUp(self):
        super().setUp()
        self.user = self.make_user(username="bearer_user", password="bearer-pass-123", nickname="令牌用户")

    def test_me_requires_token_fr_a08(self):
        response = self.client.get("/api/v1/users/me")
        self.assertEqual(response.status_code, 401, response.data)
        self.assertEqual(response.data["code"], "UNAUTHENTICATED")

    def test_malformed_bearer_returns_401_fr_a08(self):
        for header in ("Bearer invalid-token", "Token some-token", "Bearer", "Bearer a b"):
            with self.subTest(header=header):
                self.client.credentials(HTTP_AUTHORIZATION=header)
                response = self.client.get("/api/v1/users/me")
                self.assertEqual(response.status_code, 401, response.data)
                self.assertEqual(response.data["code"], "UNAUTHENTICATED")

    def test_invalid_token_on_public_endpoint_returns_401_fr_a08(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        response = self.client.post(
            "/api/v1/auth/login", {"username": "bearer_user", "password": "bearer-pass-123"}, format="json")
        self.assertEqual(response.status_code, 401, response.data)

    def test_expired_session_returns_401_fr_a08(self):
        from datetime import timedelta
        from django.utils import timezone
        token = self.login_token("bearer_user", "bearer-pass-123")
        session = AuthSession.objects.get(user=self.user)
        session.expires_at = timezone.now() - timedelta(seconds=1)
        session.save(update_fields=["expires_at"])
        self.use_token(token)
        response = self.client.get("/api/v1/users/me")
        self.assertEqual(response.status_code, 401)


class LoginRateLimitTests(UserApiTestCase):
    """FR-A-10 登录限流：每来源 IP 10 次/分钟。"""

    def setUp(self):
        super().setUp()
        self.user = self.make_user(username="throttle_user", password="throttle-pass-123", nickname="限流用户")

    @override_settings(RATE_LIMIT_ENABLED=True)
    def test_login_rate_limit_returns_429_with_retry_after_fr_a10(self):
        payload = {"username": "throttle_user", "password": "throttle-pass-123"}
        for _ in range(settings.LOGIN_RATE_LIMIT):
            response = self.client.post("/api/v1/auth/login", payload, format="json")
            self.assertEqual(response.status_code, 200, response.data)
        limited = self.client.post("/api/v1/auth/login", payload, format="json")
        self.assertEqual(limited.status_code, 429, limited.data)
        self.assertEqual(limited.data["code"], "RATE_LIMITED")
        self.assertIn("Retry-After", limited.headers)
        self.assertGreaterEqual(int(limited.headers["Retry-After"]), 1)
        # 限流按 IP：换 IP（REMOTE_ADDR）后计数独立。
        response = self.client.post("/api/v1/auth/login", payload, format="json", REMOTE_ADDR="10.0.0.9")
        self.assertEqual(response.status_code, 200, response.data)
