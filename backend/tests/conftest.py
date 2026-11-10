"""Fixtures for the contract test suite.

The demo users and dictionaries normally come from data migrations.  Tests that run with
``transaction=True`` (the MySQL concurrency cases) truncate their tables afterwards, so the
``reference_data`` fixture recreates the same rows deterministically for every test.
"""

from __future__ import annotations

import itertools
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from identity.models import DemoUser
from identity.services import issue_token
from posts.models import Campus, Category, Location, Post
from tests.support import CAMPUSES, CATEGORIES, DEMO_USERS, LOCATIONS

API = "/api/v1"


@pytest.fixture
def reference_data(db):
    now = timezone.now()
    for user_id, username, nickname, verified, mode in DEMO_USERS:
        DemoUser.objects.get_or_create(
            id=user_id,
            defaults={
                "username": username,
                "nickname": nickname,
                "bio": "",
                "is_campus_verified": verified,
                "verification_mode": mode,
                "created_at": now,
                "updated_at": now,
            },
        )
    for campus_id, name in CAMPUSES:
        Campus.objects.get_or_create(id=campus_id, defaults={"name": name})
    for category_id, name, sort_order in CATEGORIES:
        Category.objects.get_or_create(
            id=category_id, defaults={"name": name, "sort_order": sort_order}
        )
    for location_id, campus_id, name, sort_order in LOCATIONS:
        Location.objects.get_or_create(
            id=location_id,
            defaults={"campus_id": campus_id, "name": name, "sort_order": sort_order},
        )


class Actor:
    """A test client bound to one demo identity, or anonymous when ``token`` is None."""

    def __init__(self, token: str | None) -> None:
        self.client = APIClient()
        self.token = token

    def _extra(self) -> dict:
        if self.token is None:
            return {}
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def get(self, path: str, params: dict | None = None):
        return self.client.get(f"{API}{path}", params or None, **self._extra())

    def post(self, path: str, payload: dict | None = None):
        return self.client.post(
            f"{API}{path}", {} if payload is None else payload, format="json", **self._extra()
        )


@pytest.fixture
def tokens(reference_data) -> dict[str, str]:
    return {
        actor: issue_token(actor)["access_token"]
        for actor in ("alice", "bob", "finder", "outsider")
    }


@pytest.fixture
def actors(tokens) -> dict[str, Actor]:
    return {actor: Actor(token) for actor, token in tokens.items()}


@pytest.fixture
def anonymous(reference_data) -> Actor:
    return Actor(None)


@pytest.fixture
def make_post(reference_data):
    """Create a persisted post; the default is a claimable ``found`` post by ``finder``."""
    counter = itertools.count(1)

    def factory(**overrides) -> Post:
        number = next(counter)
        now = timezone.now()
        values = {
            "post_type": "found",
            "title": "图书馆拾到蓝色水杯",
            "description": "图书馆一楼自习区拾到蓝色水杯，杯身有白色条纹，请说明遗失时间与位置。",
            "category_id": "daily",
            "location_id": "library",
            "status": "open",
            "occurred_at": now - timedelta(hours=2),
            "publisher_id": "finder",
            "created_at": now,
            "updated_at": now,
        }
        values.update(overrides)
        return Post.objects.create(id=f"TEST-POST-{number}", **values)

    return factory
