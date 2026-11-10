"""A 模块领域服务：会话、注册登录登出、资料修改、校园身份绑定。

C 依赖的 require_campus_verified / user_summary / get_user_summaries / issue_session
签名保持不变。
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from common.exceptions import BusinessError
from . import selectors
from .models import AuthSession, CampusBinding, User


def require_campus_verified(user):
    if not user.is_campus_verified:
        raise BusinessError("IDENTITY_REQUIRED", "发起认领前请完成校园身份绑定（当前为演示认证）", 403)


def user_summary(user):
    return {"id": str(user.pk), "nickname": user.nickname,
            "is_campus_verified": user.is_campus_verified, "verification_mode": user.verification_mode}


def get_user_summaries(user_ids):
    return {str(user.pk): user_summary(user) for user in User.objects.filter(pk__in=user_ids)}


def issue_session(user):
    token = secrets.token_urlsafe(32)
    session = AuthSession.objects.create(user=user, token_digest=hashlib.sha256(token.encode()).hexdigest(),
                                         expires_at=timezone.now() + timedelta(hours=24))
    return token, session


def revoke_session(session):
    """撤销单个会话；其他会话不受影响。"""
    if session is not None:
        session.delete()


def register_user(username, password, nickname):
    username = username.lower()
    if User.objects.filter(username=username).exists():
        raise BusinessError("DUPLICATE_RESOURCE", "该账号已被注册", 409)
    user = User(username=username, nickname=nickname)
    user.set_password(password)
    try:
        user.save()
    except IntegrityError:
        raise BusinessError("DUPLICATE_RESOURCE", "该账号已被注册", 409)
    return user


def login_user(username, password):
    user = authenticate(username=username.lower(), password=password)
    # ModelBackend 对停用账号返回 None，与密码错误统一 401（FR-A-02）。
    if user is None or not user.is_active:
        raise BusinessError("UNAUTHENTICATED", "账号或密码错误", 401)
    return user


def update_profile(user, data):
    for field, value in data.items():
        setattr(user, field, value)
    user.save(update_fields=[*data, "updated_at"])
    user.refresh_from_db()
    return user


def bind_campus(user, campus_id, student_no, binding_code):
    """演示校园身份绑定：同一事务内完成绑定、标记身份已用、置用户认证标记。"""
    if not settings.DEMO_MODE:
        raise BusinessError("FORBIDDEN", "演示校园认证未启用", 403)
    if CampusBinding.objects.filter(user=user).exists():
        raise BusinessError("DUPLICATE_RESOURCE", "已完成校园身份绑定", 409)
    campus = selectors.get_campus(campus_id)
    if campus is None:
        raise ValidationError({"campus_id": ["校区不存在"]})
    code_digest = hashlib.sha256(binding_code.encode("utf-8")).hexdigest()
    with transaction.atomic():
        # 锁定测试身份，防止并发请求消费同一绑定码。
        identity = selectors.get_demo_identity(campus, student_no, lock=True)
        if identity is not None and identity.used_by_id is not None:
            # 与共同契约一致：身份已被他人占用属资源冲突，不与“绑定码错误”混同。
            raise BusinessError("DUPLICATE_RESOURCE", "该校园身份已被绑定", 409)
        if identity is None or not hmac.compare_digest(identity.code_digest, code_digest):
            raise ValidationError({"binding_code": ["绑定码无效或已被使用"]})
        try:
            binding = CampusBinding.objects.create(
                user=user, campus=campus, student_no=student_no, verification_mode="demo")
        except IntegrityError:
            raise BusinessError("DUPLICATE_RESOURCE", "该校园身份已被绑定", 409)
        identity.used_by = user
        identity.save(update_fields=["used_by"])
        user.is_campus_verified = True
        user.verification_mode = "demo"
        user.save(update_fields=["is_campus_verified", "verification_mode", "updated_at"])
    return binding
