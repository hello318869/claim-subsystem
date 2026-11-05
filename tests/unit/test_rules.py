from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.rules import (
    MATCH_THRESHOLD,
    RULE_VERSION,
    blocks_contact_info,
    rank_candidates,
    scan_contact_info,
    score_pair,
)


def test_mobile_email_and_id_card_are_blocked():
    assert blocks_contact_info("联系我 13812345678")
    assert blocks_contact_info("邮箱 abc.def@example.com")
    assert blocks_contact_info("身份证 11010519491231002X")
    assert blocks_contact_info("证件 110105194912310021")


def test_item_numbers_are_not_treated_as_phone_numbers():
    # Documented trade-off: short asset numbers pass; 11/18-digit runs that look like
    # contact data are intentionally rejected and must go to the private evidence field.
    assert not blocks_contact_info("编号 ASSET-2026-0042")
    assert not blocks_contact_info("资产编号 2026-0042")
    assert not blocks_contact_info("尾号 37 的校园卡")


def test_scan_reports_kind_without_echoing_full_value():
    hits = scan_contact_info("电话 13812345678")
    assert hits and hits[0].kind == "mobile"
    assert "13812345678" not in hits[0].preview


def _found(**overrides):
    base = dict(
        item_id="F-1",
        title="黑色双肩包",
        description="黑色双肩包 侧袋有蓝色水杯",
        category="bag",
        location="图书馆二楼",
        occurred_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_category_and_text_match_scores_above_threshold():
    lost = SimpleNamespace(
        title="黑色双肩包",
        description="黑色双肩包 蓝色水杯 借书卡",
        category="bag",
        location="图书馆二楼",
        occurred_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
    )
    score, reasons = score_pair(
        lost_title=lost.title,
        lost_description=lost.description,
        lost_category=lost.category,
        lost_location=lost.location,
        lost_at=lost.occurred_at,
        found_title="黑色双肩包",
        found_description="黑色双肩包 蓝色水杯",
        found_category="bag",
        found_location="图书馆二楼",
        found_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
    )
    assert score >= MATCH_THRESHOLD
    assert any("类别" in reason for reason in reasons)


def test_unrelated_item_is_filtered_out():
    lost = SimpleNamespace(
        title="黑色双肩包",
        description="黑色双肩包 蓝色水杯",
        category="bag",
        location="图书馆二楼",
        occurred_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
    )
    far = _found(title="灰色围巾", description="灰色针织围巾", category="clothing", location="体育馆", occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
    candidates = rank_candidates(lost, [far])
    assert candidates == []


def test_ranking_is_sorted_and_capped():
    lost = SimpleNamespace(
        title="黑色双肩包",
        description="黑色双肩包 蓝色水杯",
        category="bag",
        location="图书馆二楼",
        occurred_at=datetime(2026, 10, 27, tzinfo=timezone.utc),
    )
    founds = [
        _found(item_id=f"F-{i}", title="黑色双肩包", description="黑色双肩包 蓝色水杯")
        for i in range(5)
    ]
    candidates = rank_candidates(lost, founds, limit=3)
    assert len(candidates) == 3
    assert [c.score for c in candidates] == sorted((c.score for c in candidates), reverse=True)


def test_rule_version_is_frozen_string():
    assert RULE_VERSION == "rules-v1.1"
