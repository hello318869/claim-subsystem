"""FR-A-13 / 契约 v0.3：我的发布列表（A 直接查询 B 的 Post 表）。"""
from datetime import timedelta

from django.utils import timezone

from posts.models import Campus, Category, Location, Post

from . import UserApiTestCase

SUMMARY_FIELDS = {"id", "post_type", "title", "category", "campus", "location", "occurred_at",
                  "status", "cover_image", "publisher", "created_at", "updated_at"}


class MyPostsTests(UserApiTestCase):
    def setUp(self):
        super().setUp()
        self.campus = Campus.objects.create(pk="campus_main", name="主校区")
        self.category = Category.objects.create(pk="cat_keys", name="钥匙")
        self.location = Location.objects.create(pk="loc_library", name="图书馆", campus=self.campus)
        self.user = self.make_user(username="post_owner", password="owner-pass-123", nickname="发布者")
        self.other = self.make_user(username="other_user", password="other-pass-123", nickname="其他人")
        self.use_token(self.login_token("post_owner", "owner-pass-123"))

    def make_post(self, owner=None, **changes):
        data = dict(publisher_id=str((owner or self.user).pk), post_type="found", title="图书馆拾到钥匙",
                    category=self.category, location=self.location,
                    description="在图书馆二楼拾到一串钥匙，请说明具体特征。",
                    occurred_at=timezone.now() - timedelta(hours=2), handover_note="核实后交接")
        data.update(changes)
        return Post.objects.create(**data)

    def get_posts(self, query=""):
        return self.client.get(f"/api/v1/users/me/posts{query}")

    def test_requires_login_fr_a13(self):
        self.client.credentials()
        response = self.get_posts()
        self.assertEqual(response.status_code, 401, response.data)
        self.assertEqual(response.data["code"], "UNAUTHENTICATED")

    def test_only_own_posts_and_post_summary_fields_fr_a13(self):
        own = self.make_post()
        self.make_post(owner=self.other, title="别人发布的钥匙")
        response = self.get_posts()
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["id"], str(own.pk))
        self.assertEqual(set(item), SUMMARY_FIELDS)
        self.assertEqual(set(item["publisher"]), {"id", "nickname", "is_campus_verified", "verification_mode"})
        self.assertEqual(item["publisher"]["id"], str(self.user.pk))

    def test_default_contains_all_own_statuses_fr_a13(self):
        for status in ("open", "in_handover", "completed", "withdrawn"):
            self.make_post(status=status, title=f"状态 {status}")
        response = self.get_posts()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["total"], 4)
        self.assertEqual({row["status"] for row in response.data["data"]["items"]},
                         {"open", "in_handover", "completed", "withdrawn"})

    def test_filter_by_post_type_and_status_fr_a13(self):
        self.make_post(post_type="lost", title="寻物：钥匙", handover_note=None)
        self.make_post(post_type="found", title="招领：钥匙", status="open")
        self.make_post(post_type="found", title="招领：已完成", status="completed")
        response = self.get_posts("?post_type=found&status=open")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["post_type"], "found")
        self.assertEqual(data["items"][0]["status"], "open")

    def test_invalid_query_returns_400_fr_a13(self):
        for query in ("?status=unknown", "?post_type=other", "?page_size=101", "?unknown=1"):
            with self.subTest(query=query):
                response = self.get_posts(query)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                self.assertIsNone(response.data["data"])

    def test_pagination_and_ordering_fr_a13(self):
        created_at = timezone.now()
        posts = [
            self.make_post(id=f"my-post-{index}", title=f"物品 {index}", created_at=created_at)
            for index in range(3)
        ]
        first = self.get_posts("?page_size=2")
        self.assertEqual(first.status_code, 200, first.data)
        data = first.data["data"]
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["total_pages"], 2)
        self.assertEqual([row["id"] for row in data["items"]], [str(posts[2].pk), str(posts[1].pk)])

        second = self.get_posts("?page_size=2&page=2")
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual([row["id"] for row in second.data["data"]["items"]], [str(posts[0].pk)])
