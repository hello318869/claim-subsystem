"""初始化演示校园身份（FR-A-11）：幂等、仅 DEMO_MODE 可用。

- 确保共用演示校区 main 存在；
- 预置 6 个一次性测试身份（学号 20260001～20260006），只存绑定码 SHA-256 摘要；
  DEMO_BINDING_CODE 存在时统一使用该固定码（e2e 用），否则新建/重置时随机生成；
- 先为已认证的演示账号 publisher/applicant/competitor 补绑定（学号 20260001～20260003），
  再统一打印“仍未被使用”身份的绑定码：已被占用的身份不打印明文码，避免演示者拿到随即失效的码；
- 已存在的身份默认保持原码（无法还原明文）；--reset-codes 重置未使用身份的码并打印。
"""
import hashlib
import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posts.models import Campus
from users.models import CampusBinding, DemoIdentity, User

DEMO_CAMPUS_ID = "main"
STUDENT_NOS = [f"2026000{index}" for index in range(1, 7)]
BOUND_DEMO_ACCOUNTS = [("publisher", 1), ("applicant", 2), ("competitor", 3)]


def code_digest(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class Command(BaseCommand):
    help = "初始化演示校区与一次性校园身份，并为既有演示认证账号补绑定（幂等）"

    def add_arguments(self, parser):
        parser.add_argument("--reset-codes", action="store_true", help="重新生成未被使用身份的绑定码并打印")

    def _next_code(self, fixed_code):
        return fixed_code or secrets.token_urlsafe(9)

    def _bind_existing_demo_accounts(self, campus):
        """为已认证的演示账号补绑定；返回本次新绑定的用户名列表。"""
        bound = []
        for username, order in BOUND_DEMO_ACCOUNTS:
            user = User.objects.filter(username=username).first()
            if user is None or not user.is_campus_verified or user.verification_mode != "demo":
                continue
            if CampusBinding.objects.filter(user=user).exists():
                continue
            student_no = f"2026000{order}"
            identity = DemoIdentity.objects.filter(campus=campus, student_no=student_no).first()
            if identity is None or identity.used_by_id not in (None, user.pk):
                continue
            if CampusBinding.objects.filter(campus=campus, student_no=student_no).exists():
                continue
            CampusBinding.objects.create(user=user, campus=campus, student_no=student_no, verification_mode="demo")
            identity.used_by = user
            identity.save(update_fields=["used_by"])
            user.is_campus_verified = True
            user.verification_mode = "demo"
            user.save(update_fields=["is_campus_verified", "verification_mode", "updated_at"])
            bound.append(username)
        return bound

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError("仅允许在 DEMO_MODE=true 时初始化演示身份")
        fixed_code = os.environ.get("DEMO_BINDING_CODE") or None
        if fixed_code is not None and not 6 <= len(fixed_code) <= 64:
            raise CommandError("DEMO_BINDING_CODE 长度必须为 6～64")

        campus, _ = Campus.objects.get_or_create(pk=DEMO_CAMPUS_ID, defaults={"name": "主校区"})
        generated_codes = {}  # 学号 -> 本次生成的绑定码明文（旧码无法还原，不在其中）
        for student_no in STUDENT_NOS:
            identity = DemoIdentity.objects.filter(campus=campus, student_no=student_no).first()
            if identity is None:
                code = self._next_code(fixed_code)
                DemoIdentity.objects.create(campus=campus, student_no=student_no, code_digest=code_digest(code))
                generated_codes[student_no] = code
            elif options["reset_codes"] and identity.used_by_id is None:
                code = self._next_code(fixed_code)
                identity.code_digest = code_digest(code)
                identity.save(update_fields=["code_digest"])
                generated_codes[student_no] = code

        # 先补绑定，再打印可用码：否则先打印的码可能在随后的自动绑定中立即失效。
        bound = self._bind_existing_demo_accounts(campus)
        if bound:
            self.stdout.write(f"已为演示认证账号补绑定：{', '.join(bound)}（学号 20260001～20260003）")

        available = list(DemoIdentity.objects.filter(campus=campus, used_by__isnull=True).order_by("student_no"))
        fresh_codes = [(row.student_no, generated_codes[row.student_no])
                       for row in available if row.student_no in generated_codes]
        if fresh_codes:
            self.stdout.write("本次可用一次性绑定码（明文只显示这一次，请妥善保存）：")
            for student_no, code in fresh_codes:
                self.stdout.write(f"  学号 {student_no}  绑定码 {code}")
        stale_count = len(available) - len(fresh_codes)
        if stale_count:
            self.stdout.write(f"已有身份 {stale_count} 个可用（原码无法还原）；--reset-codes 可重置未使用身份")
        if not available:
            self.stdout.write("已有身份均已被使用；--reset-codes 只重置未使用身份。")
        self.stdout.write(f"校区 {campus.pk} 的演示身份就绪；当前可用身份 {len(available)} 个。")
