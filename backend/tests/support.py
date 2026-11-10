"""Shared test data and helpers."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

ACTORS = ("alice", "bob", "finder", "outsider")

PROOF = "蓝色杯底有一处划痕，杯盖内侧贴着一张卡通贴纸。"
RIVAL_PROOF = "杯身有磨损，杯盖有裂纹，杯柄上缠着一圈胶带。"

DEMO_USERS = (
    # id, username, nickname, is_campus_verified, verification_mode
    ("alice", "alice", "小林", True, "demo"),
    ("bob", "bob", "小周", True, "demo"),
    ("finder", "finder", "小陈", True, "demo"),
    ("outsider", "outsider", "访客", False, None),
)

CAMPUSES = (("main", "主校区"),)

CATEGORIES = (
    ("keys", "钥匙", 1),
    ("daily", "日用品", 2),
    ("books", "书籍", 3),
    ("electronics", "电子产品", 4),
    ("cards", "证件", 5),
    ("clothing", "衣物", 6),
    ("other", "其他", 7),
)

LOCATIONS = (
    ("library", "main", "图书馆", 1),
    ("gym", "main", "体育馆", 2),
    ("canteen", "main", "食堂", 3),
    ("teaching", "main", "教学楼", 4),
)


def apply_claim(actors, post_id: str, actor: str = "alice", text: str = PROOF) -> str:
    """Create a pending claim and return its id."""
    response = actors[actor].post(
        "/claims", {"post_id": post_id, "verification_text": text}
    )
    assert response.status_code == 201, response.content
    return response.json()["data"]["id"]


def accept_claim(actors, claim_id: str, actor: str = "finder", note: str | None = None):
    payload = {} if note is None else {"decision_note": note}
    return actors[actor].post(f"/claims/{claim_id}/accept", payload)


def post_payload(post_id: str, **overrides) -> dict:
    """Defaults for a database post created directly by a test."""
    now = timezone.now()
    values = {
        "post_type": "found",
        "title": "图书馆拾到蓝色水杯",
        "description": "",
        "category_id": "daily",
        "location_id": "library",
        "status": "open",
        "occurred_at": now - timedelta(hours=2),
        "publisher_id": "finder",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return {"id": post_id, **values}
