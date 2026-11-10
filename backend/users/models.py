from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """A 的最小身份适配模型；演示认证标记仅由 seed_demo 写入。"""
    nickname = models.CharField(max_length=30)
    bio = models.CharField(max_length=200, blank=True)
    is_campus_verified = models.BooleanField(default=False)
    verification_mode = models.CharField(max_length=16, null=True, default=None)
    updated_at = models.DateTimeField(auto_now=True)


class AuthSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()


class CampusBinding(models.Model):
    """校园身份绑定：一用户一条；校区+学号联合唯一。"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="campus_binding")
    campus = models.ForeignKey("posts.Campus", on_delete=models.PROTECT)
    student_no = models.CharField(max_length=20)
    verification_mode = models.CharField(max_length=16, default="demo")
    verified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campus", "student_no"], name="uniq_campus_student_no")]
        ordering = ["-verified_at"]


class DemoIdentity(models.Model):
    """演示用一次性校园身份：只存绑定码 SHA-256 摘要，不存明文。"""
    campus = models.ForeignKey("posts.Campus", on_delete=models.PROTECT)
    student_no = models.CharField(max_length=20)
    code_digest = models.CharField(max_length=64)
    used_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campus", "student_no"], name="uniq_demo_identity")]
