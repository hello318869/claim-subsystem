"""FR-A-04/05：查看与修改本人资料。"""
import json
import time

from users.models import User

from . import UserApiTestCase
from .test_auth import USER_SELF_FIELDS


class ProfileViewTests(UserApiTestCase):
    """FR-A-04 查看本人资料。"""

    def setUp(self):
        super().setUp()
        self.user = self.make_user(username="profile_user", password="profile-pass-123", nickname="资料用户")
        self.use_token(self.login_token("profile_user", "profile-pass-123"))

    def test_get_me_returns_user_self_fr_a04(self):
        response = self.client.get("/api/v1/users/me")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(set(data), USER_SELF_FIELDS)
        self.assertEqual(data["id"], str(self.user.pk))
        self.assertEqual(data["username"], "profile_user")
        self.assertEqual(data["nickname"], "资料用户")
        self.assertEqual(data["bio"], "")
        self.assertFalse(data["is_campus_verified"])
        self.assertTrue(data["created_at"].endswith("Z"))
        self.assertTrue(data["updated_at"].endswith("Z"))

    def test_get_me_requires_token_fr_a04(self):
        self.client.credentials()
        response = self.client.get("/api/v1/users/me")
        self.assertEqual(response.status_code, 401, response.data)
        self.assertEqual(response.data["code"], "UNAUTHENTICATED")

    def test_get_me_never_exposes_password_or_hash_fr_a04(self):
        raw = json.dumps(self.client.get("/api/v1/users/me").data).lower()
        self.assertNotIn("password", raw)
        self.assertNotIn("pbkdf2", raw)
        self.assertNotIn("hash", raw)


class ProfileUpdateTests(UserApiTestCase):
    """FR-A-05 修改本人资料。"""

    def setUp(self):
        super().setUp()
        self.user = self.make_user(username="editor", password="editor-pass-123", nickname="旧昵称")
        self.use_token(self.login_token("editor", "editor-pass-123"))

    def patch(self, payload):
        return self.client.patch("/api/v1/users/me", payload, format="json")

    def test_patch_nickname_success_fr_a05(self):
        response = self.patch({"nickname": "新昵称"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["nickname"], "新昵称")
        self.assertEqual(set(response.data["data"]), USER_SELF_FIELDS)
        self.user.refresh_from_db()
        self.assertEqual(self.user.nickname, "新昵称")

    def test_patch_bio_only_keeps_nickname_fr_a05(self):
        response = self.patch({"bio": "喜欢在图书馆自习。"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["bio"], "喜欢在图书馆自习。")
        self.assertEqual(response.data["data"]["nickname"], "旧昵称")
        response = self.patch({"bio": ""})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["bio"], "")

    def test_patch_empty_object_returns_400_fr_a05(self):
        response = self.patch({})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertTrue(response.data["errors"])

    def test_patch_unknown_or_readonly_fields_returns_400_fr_a05(self):
        for payload in ({"username": "hacked"}, {"is_campus_verified": True}, {"password": "new-pass-123"},
                        {"verification_mode": "demo"}, {"id": "1"}):
            with self.subTest(payload=payload):
                response = self.patch(payload)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                self.assertTrue(set(payload) & set(response.data["errors"]))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "editor")
        self.assertFalse(self.user.is_campus_verified)

    def test_patch_length_boundaries_fr_a05(self):
        self.assertEqual(self.patch({"nickname": "名"}).status_code, 200)
        self.assertEqual(self.patch({"nickname": "名" * 30}).status_code, 200)
        self.assertEqual(self.patch({"nickname": "名" * 31}).status_code, 400)
        self.assertEqual(self.patch({"bio": "字" * 200}).status_code, 200)
        self.assertEqual(self.patch({"bio": "字" * 201}).status_code, 400)

    def test_patch_trims_whitespace_fr_a05(self):
        response = self.patch({"nickname": "  昵称  ", "bio": "  简介  "})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["nickname"], "昵称")
        self.assertEqual(response.data["data"]["bio"], "简介")
        self.assertEqual(self.patch({"nickname": "   "}).status_code, 400)

    def test_patch_updates_updated_at_fr_a05(self):
        before = self.client.get("/api/v1/users/me").data["data"]["updated_at"]
        time.sleep(0.02)
        response = self.patch({"nickname": "更新后的昵称"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(response.data["data"]["updated_at"], before)
        self.assertEqual(response.data["data"]["created_at"], self.client.get("/api/v1/users/me").data["data"]["created_at"])

    def test_patch_requires_token_fr_a05(self):
        self.client.credentials()
        response = self.patch({"nickname": "未登录"})
        self.assertEqual(response.status_code, 401, response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.nickname, "旧昵称")
