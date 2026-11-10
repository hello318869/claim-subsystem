"""Unrelated posts must not contend for locks on their shared dictionary rows."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection, connections, transaction
from django.utils import timezone

from posts import services
from posts.models import Campus, Category, Location, Post
from posts.views import _load_post

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.mysql]


def _load_for_post_write(post_id):
    return _load_post(post_id, for_update=True, with_images=False)


def _load_for_claim_write(post_id):
    return services.get_post_for_claim(post_id, lock=True)


def _load_for_claim_batch(post_id):
    return services.get_posts_for_claims([post_id], lock=True)[post_id]


def _reserve_for_handover(post_id):
    return services.set_handover_state(post_id, "reserve")


def _lock_in_worker(load, post_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION innodb_lock_wait_timeout = 2")
        with transaction.atomic():
            return load(post_id).id
    finally:
        connections.close_all()


@pytest.mark.parametrize(
    "load",
    [
        pytest.param(_load_for_post_write, id="post-write"),
        pytest.param(_load_for_claim_write, id="claim-write"),
        pytest.param(_load_for_claim_batch, id="claim-batch"),
        pytest.param(_reserve_for_handover, id="handover"),
    ],
)
def test_distinct_posts_can_be_locked_when_their_dictionary_is_shared(load):
    if connection.vendor != "mysql":
        pytest.skip("需要 MySQL 行级锁")

    campus = Campus.objects.create(id="lock-campus", name="测试校区")
    category = Category.objects.create(id="lock-category", name="测试类别")
    location = Location.objects.create(id="lock-location", campus=campus, name="测试地点")
    post_fields = {
        "post_type": "lost",
        "title": "行锁范围测试",
        "description": "此信息与另一条信息共享分类、校区和地点。",
        "category": category,
        "location": location,
        "publisher_id": "lock-publisher",
        "occurred_at": timezone.now(),
    }
    first = Post.objects.create(id="lock-first", **post_fields)
    second = Post.objects.create(id="lock-second", **post_fields)

    # Wait for the other connection to finish while this transaction still owns the first lock.
    with ThreadPoolExecutor(max_workers=1) as worker, transaction.atomic():
        assert load(first.id).id == first.id
        future = worker.submit(_lock_in_worker, load, second.id)
        assert future.result(timeout=15) == second.id
