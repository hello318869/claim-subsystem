"""Public listing DTOs, filters and pagination."""

from __future__ import annotations

from typing import Any

import pytest

from claimtest.api import (
    Api,
    Paths,
    assert_error,
    expect_status,
    json_object,
    unwrap_entity,
    unwrap_items,
)
from claimtest.privacy import assert_no_identity_fields

PUBLIC_LISTING_FIELDS = (
    "id",
    "title",
    "category",
    "occurred_at",
    "location",
    "description",
    "status",
)


def _ids(items: list[Any]) -> set[str]:
    return {str(item["id"]) for item in items if isinstance(item, dict) and "id" in item}


def _collect_listings(
    api: Api,
    actor: str,
    *,
    kind: str,
    mine: bool | None = None,
    page_size: int = 50,
    max_pages: int = 40,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params: dict[str, Any] = {"kind": kind, "page": page, "page_size": page_size}
        if mine is not None:
            params["mine"] = "true" if mine else "false"
        response = api.get(Paths.LISTINGS, actor=actor, params=params)
        expect_status(response, 200)
        items = unwrap_items(json_object(response))
        page_items = [item for item in items if isinstance(item, dict)]
        collected.extend(page_items)
        if len(page_items) < page_size:
            break
    return collected


def test_public_found_listing_detail(api: Api, scenario):
    response = api.get(Paths.listing(scenario.found_id), actor="bob")
    expect_status(response, 200)
    entity = unwrap_entity(response)
    for field in PUBLIC_LISTING_FIELDS:
        assert field in entity, f"public listing misses {field!r}"
    assert str(entity["id"]) == str(scenario.found_id)
    assert entity["title"]
    assert_no_identity_fields(entity, context="public listing detail")


def test_public_listing_dto_has_no_identity_mapping(api: Api):
    response = api.get(
        Paths.LISTINGS, actor="alice", params={"kind": "found", "page": 1, "page_size": 20}
    )
    expect_status(response, 200)
    payload = json_object(response)
    items = unwrap_items(payload)
    assert items, "seed data should expose at least one found listing"
    assert_no_identity_fields(payload, context="public listing page")


def test_mine_filter_returns_only_owner_rows(api: Api, scenario):
    finder_rows = _collect_listings(api, "finder", kind="found", mine=True)
    assert str(scenario.found_id) in _ids(finder_rows)

    bob_rows = _collect_listings(api, "bob", kind="found", mine=True)
    assert str(scenario.found_id) not in _ids(bob_rows)


def test_pagination_pages_do_not_overlap(api: Api):
    first = api.get(
        Paths.LISTINGS, actor="alice", params={"kind": "lost", "page": 1, "page_size": 5}
    )
    second = api.get(
        Paths.LISTINGS, actor="alice", params={"kind": "lost", "page": 2, "page_size": 5}
    )
    expect_status(first, 200)
    expect_status(second, 200)
    first_ids = _ids(unwrap_items(json_object(first)))
    second_ids = _ids(unwrap_items(json_object(second)))
    assert first_ids, "seed data should expose lost listings for pagination"
    assert len(first_ids) <= 5
    assert len(second_ids) <= 5
    assert first_ids.isdisjoint(second_ids)


def test_invalid_kind_is_422(api: Api):
    response = api.get(
        Paths.LISTINGS, actor="alice", params={"kind": "unknown", "page": 1, "page_size": 20}
    )
    assert_error(response, 422)


def test_listing_not_found_is_404(api: Api):
    response = api.get(Paths.listing(987654321), actor="alice")
    assert_error(response, 404)


def test_listing_detail_requires_bearer(api: Api, scenario):
    response = api.raw("GET", Paths.listing(scenario.found_id))
    assert_error(response, 401)
