"""Private image metadata follows the B detail and C public-summary boundaries."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from identity.models import DemoUser
from identity.services import issue_token
from posts.models import Campus, Category, Location, Post, PostImage


class ImageMetadataVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for name in ("b-meta-lost", "b-meta-found"):
            DemoUser.objects.create(id=name, username=name, nickname=name, is_campus_verified=True)
        campus = Campus.objects.create(id="b-meta-campus", name="测试校区")
        category = Category.objects.create(id="b-meta-category", name="测试类别")
        location = Location.objects.create(id="b-meta-location", campus=campus, name="测试位置")
        happened = timezone.now() - timedelta(days=1)
        cls.lost = Post.objects.create(
            publisher_id="b-meta-lost", post_type="lost", title="遗失蓝色钥匙", occurred_at=happened,
            category=category, location=location,
            description="钥匙在图书馆二楼遗失，蓝色挂绳，钥匙扣是一只小猫。",
        )
        cls.found = Post.objects.create(
            publisher_id="b-meta-found", post_type="found", title="拾到蓝色钥匙", occurred_at=happened,
            category=category, location=location,
            description="在图书馆二楼靠窗座位拾到一串钥匙，蓝色挂绳。",
        )

    def test_public_cover_skips_private_metadata_and_detail_requires_login(self):
        private = PostImage.objects.create(
            post=self.found, owner_id="b-meta-found", file="post-images/private-test.png",
            mime_type="image/png", size_bytes=50, sort_order=0, alt_text="仅登录可读的图片说明", is_public=False,
        )
        anonymous = APIClient()
        authenticated = APIClient()
        authenticated.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_token('b-meta-lost')['access_token']}")
        detail_path = f"/api/v1/posts/{self.found.pk}"
        match_path = f"/api/v1/posts/{self.lost.pk}/matches"

        detail = anonymous.get(detail_path)
        assert detail.status_code == 200
        assert detail.json()["data"]["images"] == []
        assert detail.json()["data"]["cover_image"] is None
        match = authenticated.get(match_path)
        assert match.status_code == 200
        assert match.json()["data"]["items"][0]["post"]["cover_image"] is None

        public = PostImage.objects.create(
            post=self.found, owner_id="b-meta-found", file="post-images/public-test.png",
            mime_type="image/png", size_bytes=60, sort_order=1, alt_text="可以公开的图片说明", is_public=True,
        )
        listed = anonymous.get("/api/v1/posts", {"category_id": self.found.category_id, "post_type": "found"})
        assert listed.status_code == 200
        assert listed.json()["data"]["items"][0]["cover_image"]["id"] == str(public.id)
        assert anonymous.get(detail_path).json()["data"]["images"][0]["id"] == str(public.id)
        assert authenticated.get(match_path).json()["data"]["items"][0]["post"]["cover_image"]["id"] == str(public.id)
        assert [image["id"] for image in authenticated.get(detail_path).json()["data"]["images"]] == [
            str(private.id), str(public.id),
        ]
