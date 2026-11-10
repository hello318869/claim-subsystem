"""FR-A-06/07/10、NFR-A-01/03：校园身份绑定、脱敏、限流与并发。"""
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from posts.models import Campus
from users.models import CampusBinding, DemoIdentity, User

from . import UserApiTestCase

BINDING_FIELDS = {"campus_id", "student_no_masked", "verification_mode", "verified_at"}


def digest(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class CampusBindingTests(UserApiTestCase):
    """FR-A-06 查看绑定 / FR-A-07 演示绑定。"""

    def setUp(self):
        super().setUp()
        self.campus = Campus.objects.create(pk="campus_main", name="主校区")
        self.user = self.make_user(username="bind_user", password="bind-pass-123", nickname="绑定用户")
        self.code = "bind-code-0001"
        self.identity = DemoIdentity.objects.create(
            campus=self.campus, student_no="20260001", code_digest=digest(self.code))
        self.use_token(self.login_token("bind_user", "bind-pass-123"))

    def bind(self, **overrides):
        payload = {"campus_id": "campus_main", "student_no": "20260001", "binding_code": self.code}
        payload.update(overrides)
        return self.client.post("/api/v1/users/me/campus-binding", payload, format="json")

    def test_get_binding_before_bind_returns_null_fr_a06(self):
        response = self.client.get("/api/v1/users/me/campus-binding")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["data"])

    def test_bind_success_sets_verification_and_binding_fr_a07(self):
        response = self.bind()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["code"], "OK")
        data = response.data["data"]
        self.assertEqual(set(data), BINDING_FIELDS)
        self.assertEqual(data["campus_id"], "campus_main")
        self.assertEqual(data["student_no_masked"], "****0001")
        self.assertEqual(data["verification_mode"], "demo")
        self.assertTrue(data["verified_at"].endswith("Z"))
        self.assertNotIn("20260001", json.dumps(data))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_campus_verified)
        self.assertEqual(self.user.verification_mode, "demo")
        binding = CampusBinding.objects.get(user=self.user)
        self.assertEqual((binding.campus_id, binding.student_no), ("campus_main", "20260001"))
        self.identity.refresh_from_db()
        self.assertEqual(self.identity.used_by_id, self.user.pk)

    def test_get_binding_after_bind_returns_masked_view_fr_a06(self):
        self.assertEqual(self.bind().status_code, 201)
        response = self.client.get("/api/v1/users/me/campus-binding")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data["data"]), BINDING_FIELDS)
        self.assertEqual(response.data["data"]["student_no_masked"], "****0001")

    def test_rebind_returns_409_fr_a07(self):
        self.assertEqual(self.bind().status_code, 201)
        response = self.bind()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "DUPLICATE_RESOURCE")
        self.assertEqual(CampusBinding.objects.filter(user=self.user).count(), 1)

    def test_wrong_code_on_existing_identity_returns_400_fr_a07(self):
        """身份存在但绑定码摘要不匹配 → 400，错误归 binding_code（区别于“已被占用”的 409）。"""
        response = self.bind(binding_code="wrong-code-99")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertEqual(response.data["errors"]["binding_code"], ["绑定码无效或已被使用"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_campus_verified)
        self.assertIsNone(self.user.verification_mode)
        self.assertFalse(CampusBinding.objects.filter(user=self.user).exists())
        self.identity.refresh_from_db()
        self.assertIsNone(self.identity.used_by_id)

    def test_unknown_campus_returns_400_campus_id_error_fr_a07(self):
        response = self.bind(campus_id="campus_missing")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("campus_id", response.data["errors"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_campus_verified)

    def test_invalid_student_no_returns_400_student_no_error_fr_a07(self):
        for student_no in ("12345", "2026-0001", "1" * 21):
            with self.subTest(student_no=student_no):
                response = self.bind(student_no=student_no)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("student_no", response.data["errors"])

    def test_identity_used_by_other_returns_409_fr_a07(self):
        """共同契约 §4：同一校园身份被重复绑定返回 409，不与“绑定码错误”混同。"""
        other = self.make_user(username="owner_other", password="other-pass-123", nickname="他人")
        CampusBinding.objects.create(user=other, campus=self.campus, student_no="20260001")
        self.identity.used_by = other
        self.identity.save(update_fields=["used_by"])
        response = self.bind()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "DUPLICATE_RESOURCE")
        self.assertIsNone(response.data["data"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_campus_verified)
        self.assertFalse(CampusBinding.objects.filter(user=self.user).exists())

    def test_binding_requires_token_fr_a07(self):
        self.client.credentials()
        response = self.bind()
        self.assertEqual(response.status_code, 401, response.data)

    def test_binding_unknown_or_readonly_field_returns_400_nfr_a04(self):
        response = self.bind(user_id="1")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("user_id", response.data["errors"])


class BindingRateLimitTests(UserApiTestCase):
    """FR-A-10 绑定限流：每登录用户 5 次/分钟。"""

    def setUp(self):
        super().setUp()
        self.campus = Campus.objects.create(pk="campus_main", name="主校区")
        self.user = self.make_user(username="bind_limiter", password="limit-pass-123", nickname="限流用户")
        self.use_token(self.login_token("bind_limiter", "limit-pass-123"))

    @override_settings(RATE_LIMIT_ENABLED=True)
    def test_binding_rate_limit_returns_429_with_retry_after_fr_a10(self):
        payload = {"campus_id": "campus_main", "student_no": "20260002", "binding_code": "wrong-code-01"}
        for _ in range(settings.BINDING_RATE_LIMIT):
            response = self.client.post("/api/v1/users/me/campus-binding", payload, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        limited = self.client.post("/api/v1/users/me/campus-binding", payload, format="json")
        self.assertEqual(limited.status_code, 429, limited.data)
        self.assertEqual(limited.data["code"], "RATE_LIMITED")
        self.assertIn("Retry-After", limited.headers)
        self.assertGreaterEqual(int(limited.headers["Retry-After"]), 1)


class CampusBindingConcurrencyTests(TransactionTestCase):
    """NFR-A-03 并发绑定同一身份最多一个成功（线程 + 独立连接，参考 tests/test_concurrency.py）。"""

    def setUp(self):
        self.campus = Campus.objects.create(pk="campus_main", name="主校区")
        self.code = "race-code-0001"
        self.identity = DemoIdentity.objects.create(
            campus=self.campus, student_no="20260005", code_digest=digest(self.code))
        self.first = User.objects.create_user(username="racer_a", password="race-pass-123", nickname="甲")
        self.second = User.objects.create_user(username="racer_b", password="race-pass-123", nickname="乙")

    def race(self, operations):
        barrier = Barrier(len(operations))

        def run(user):
            close_old_connections()
            client = APIClient()
            client.force_authenticate(user)
            try:
                barrier.wait(timeout=10)
                response = client.post("/api/v1/users/me/campus-binding", {
                    "campus_id": "campus_main", "student_no": "20260005", "binding_code": self.code,
                }, format="json")
                return response.status_code, response.data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))

    def test_concurrent_same_identity_has_single_winner_fr_a10_nfr_a03(self):
        responses = self.race([self.first, self.second])
        # 胜者 201；败者读到已被占用的身份，按共同契约返回 409（资源冲突）。
        self.assertEqual(sorted(code for code, _ in responses), [201, 409], responses)
        self.assertEqual(CampusBinding.objects.count(), 1)
        self.identity.refresh_from_db()
        self.assertIsNotNone(self.identity.used_by_id)
        self.assertEqual(User.objects.filter(is_campus_verified=True).count(), 1)
        binding = CampusBinding.objects.get()
        self.assertEqual(binding.user_id, self.identity.used_by_id)


class SeedDemoUsersTests(UserApiTestCase):
    """FR-A-11 演示数据初始化：幂等、自动绑定既有演示认证账号、不认证普通用户。"""

    def setUp(self):
        super().setUp()
        self.publisher = self.make_user(username="publisher", password="seed-pass-123", nickname="拾获者",
                                        is_campus_verified=True, verification_mode="demo")
        self.unverified = self.make_user(username="unverified", password="seed-pass-123", nickname="未认证")

    def run_seed(self, *args):
        out = io.StringIO()
        call_command("seed_demo_users", *args, stdout=out)
        return out.getvalue()

    def test_seed_binds_then_prints_only_unused_codes_fr_a11(self):
        output = self.run_seed()
        self.assertEqual(DemoIdentity.objects.count(), 6)
        self.assertIn("已为演示认证账号补绑定", output)
        # 先补绑定、后打印：20260001 已被 publisher 占用，不得再打印其明文码。
        self.assertLess(output.index("已为演示认证账号补绑定"), output.index("一次性绑定码"))
        code_lines = [line for line in output.splitlines() if "学号" in line and "绑定码" in line]
        self.assertEqual(len(code_lines), 5)
        self.assertFalse(any("20260001" in line for line in code_lines))
        self.assertTrue(any("20260002" in line for line in code_lines))
        self.assertNotIn("20260001  绑定码", output)
        self.assertEqual(CampusBinding.objects.count(), 1)
        self.assertEqual(CampusBinding.objects.get().user_id, self.publisher.pk)
        self.publisher.refresh_from_db()
        self.assertTrue(self.publisher.is_campus_verified)
        self.unverified.refresh_from_db()
        self.assertFalse(self.unverified.is_campus_verified)
        self.assertFalse(User.objects.filter(username="unverified", is_campus_verified=True).exists())
        # 身份绑定码只存摘要，不存明文。
        self.assertTrue(all(len(row.code_digest) == 64 for row in DemoIdentity.objects.all()))

    def test_seed_is_idempotent_fr_a11(self):
        self.run_seed()
        identity_ids = set(DemoIdentity.objects.values_list("pk", flat=True))
        output = self.run_seed()
        self.assertEqual(set(DemoIdentity.objects.values_list("pk", flat=True)), identity_ids)
        self.assertEqual(DemoIdentity.objects.count(), 6)
        self.assertEqual(CampusBinding.objects.count(), 1)
        self.assertIn("已有身份 5 个可用", output)
        self.assertNotIn("绑定码", output)

    def test_seed_reset_codes_only_for_unused_identities_fr_a11(self):
        self.run_seed()
        used_digest = DemoIdentity.objects.get(student_no="20260001").code_digest
        output = self.run_seed("--reset-codes")
        self.assertEqual(DemoIdentity.objects.get(student_no="20260001").code_digest, used_digest)
        # 只重置未使用身份；已绑定身份不打印明文码。
        code_lines = [line for line in output.splitlines() if "学号" in line and "绑定码" in line]
        self.assertEqual(len(code_lines), 5)
        self.assertFalse(any("20260001" in line for line in code_lines))
        self.assertTrue(any("20260002" in line for line in code_lines))

    def test_seed_requires_demo_mode_fr_a11(self):
        with override_settings(DEMO_MODE=False):
            with self.assertRaises(CommandError):
                self.run_seed()
