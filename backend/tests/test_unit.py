"""Pure helpers: time formatting, paging, text rules, privacy scan and matching tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from claims.services.matching import _title_bigrams
from common.clock import iso
from common.errors import AppError, error_payload, flatten_errors
from common.privacy import blocks_contact_info, scan_contact_info
from common.responses import page_payload
from common.serializers import clean_text


def test_iso_returns_none_for_null():
    assert iso(None) is None


def test_iso_formats_aware_utc_with_z():
    moment = datetime(2026, 10, 7, 2, 0, 0, tzinfo=UTC)
    assert iso(moment) == "2026-10-07T02:00:00Z"


def test_iso_treats_naive_values_as_utc():
    assert iso(datetime(2026, 10, 7, 2, 0, 0)) == "2026-10-07T02:00:00Z"


def test_iso_converts_other_offsets_to_utc():
    beijing = timezone(timedelta(hours=8))
    assert iso(datetime(2026, 10, 7, 10, 0, 0, tzinfo=beijing)) == "2026-10-07T02:00:00Z"


def test_page_payload_zero_total_has_zero_pages():
    assert page_payload([], 0, 1, 20) == {
        "items": [],
        "page": 1,
        "page_size": 20,
        "total": 0,
        "total_pages": 0,
    }


def test_page_payload_rounds_up_total_pages():
    assert page_payload([], 21, 2, 20)["total_pages"] == 2
    assert page_payload([], 20, 1, 20)["total_pages"] == 1


def test_clean_text_strips_and_measures_characters():
    assert clean_text("  蓝色水杯  ", "title", 2, 60) == "蓝色水杯"


@pytest.mark.parametrize(
    ("value", "minimum", "maximum"),
    (
        ("短", 2, 60),
        ("长" * 61, 2, 60),
        ("   ", 2, 60),
        (None, 2, 60),
    ),
)
def test_clean_text_rejects_out_of_range_values(value, minimum, maximum):
    with pytest.raises(AppError) as caught:
        clean_text(value, "title", minimum, maximum)
    assert caught.value.status_code == 400
    assert caught.value.code == "VALIDATION_ERROR"
    assert "title" in caught.value.errors


def test_error_payload_shape():
    assert error_payload("NOT_FOUND", "不存在") == {
        "code": "NOT_FOUND",
        "message": "不存在",
        "data": None,
        "errors": {},
    }


def test_app_error_puts_message_under_field():
    error = AppError(400, "VALIDATION_ERROR", "太长", field="content")
    assert error.errors == {"content": ["太长"]}


def test_flatten_errors_accepts_dict_list_and_string():
    assert flatten_errors({"title": ["必填"]}) == {"title": ["必填"]}
    assert flatten_errors(["整体错误"]) == {"non_field_errors": ["整体错误"]}
    assert flatten_errors("单个错误") == {"non_field_errors": ["单个错误"]}


@pytest.mark.parametrize(
    "text",
    (
        "联系我 13800138000",
        "邮箱 student@example.com",
        "身份证 11010519491231002X",
    ),
)
def test_contact_information_is_blocked(text):
    assert blocks_contact_info(text)


@pytest.mark.parametrize(
    "text",
    (
        "编号 ASSET-2026-0042 的物品已交到前台",
        "杯底有贴纸，请失主说明颜色",
        "",
    ),
)
def test_ordinary_text_is_not_blocked(text):
    assert not blocks_contact_info(text)


def test_scan_reports_kind_without_full_value():
    hits = scan_contact_info("电话 13800138000")
    assert [hit.kind for hit in hits] == ["mobile"]
    assert hits[0].preview == "1380***"
    assert "00138000" not in hits[0].preview


def test_title_bigrams_ignore_case_spaces_and_punctuation():
    assert _title_bigrams("蓝色水杯") == {("蓝", "色"), ("色", "水"), ("水", "杯")}
    assert _title_bigrams("Hello, World!") == {
        ("h", "e"),
        ("e", "l"),
        ("l", "l"),
        ("l", "o"),
        ("o", "w"),
        ("w", "o"),
        ("o", "r"),
        ("r", "l"),
        ("l", "d"),
    }


def test_title_bigrams_empty_for_short_titles():
    assert _title_bigrams("杯") == set()
    assert _title_bigrams("，。！") == set()
