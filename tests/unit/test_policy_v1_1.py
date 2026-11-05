"""Regression tests for the v1.0.1 defect fixes that need no database."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import idempotency
from app.config import Settings
from app.rules import MIN_TEXT_OVERLAP, RULE_VERSION, rank_candidates
from app.schemas import ClaimCreateRequest, MessageRequest, ReasonRequest

FIXTURE = "tests/fixtures/matching-v1.json"


def _settings(secret: str = "unit-secret") -> Settings:
    return Settings(
        environment="test",
        database_url="mysql+pymysql://unused/unused",
        auth_secret=secret,
        handover_secret=secret + ":handover",
        demo_mode=True,
    )


# --- D4: whitespace-only bodies -------------------------------------------------


def test_blank_evidence_is_rejected_after_strip():
    with pytest.raises(ValidationError):
        ClaimCreateRequest(item_id="F-1", evidence_text="   ")
    with pytest.raises(ValidationError):
        ClaimCreateRequest(item_id="F-1", evidence_text="\n\t")


def test_blank_message_and_reason_are_rejected():
    with pytest.raises(ValidationError):
        MessageRequest(text=" \n\t ")
    with pytest.raises(ValidationError):
        ReasonRequest(reason="   ")


def test_evidence_is_stripped_and_optional_number_collapses():
    request = ClaimCreateRequest(item_id=" F-1 ", evidence_text="  有蓝色水杯  ", item_number="   ")
    assert request.item_id == "F-1"
    assert request.evidence_text == "有蓝色水杯"
    assert request.item_number is None


# --- D2: idempotency fingerprint ------------------------------------------------


def test_fingerprint_is_keyed_and_domain_separated():
    settings = _settings()
    payload = {"item_id": "F-1", "code": "12345678"}
    first = idempotency.fingerprint(settings, "alice", "handover.confirm", payload)
    assert len(first) == 64
    assert first != idempotency.fingerprint(_settings("other-secret"), "alice", "handover.confirm", payload)
    assert first != idempotency.fingerprint(settings, "bob", "handover.confirm", payload)
    assert first != idempotency.fingerprint(settings, "alice", "claim.create", payload)
    assert first != idempotency.fingerprint(settings, "alice", "handover.confirm", {**payload, "code": "00000000"})
    canonical = json.dumps(
        {"operation": "handover.confirm", "payload": payload}, sort_keys=True, ensure_ascii=False
    )
    bare = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert first != bare, "a bare digest of an 8-digit code would be enumerable"


# --- D3: rules-v1.1 text-evidence gate ------------------------------------------


def _load_cases():
    with open(FIXTURE, encoding="utf-8") as handle:
        data = json.load(handle)
    founds = [
        SimpleNamespace(
            item_id=row["label"],
            title=row["title"],
            category=row["category"],
            description=row["description"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            location=row["location"],
        )
        for row in data["found_records"] + data["distractors"]
    ]
    return data, founds


def _lost(query):
    return SimpleNamespace(
        title=query["title"],
        category=query["category"],
        description=query["description"],
        occurred_at=datetime.fromisoformat(query["occurred_at"]),
        location=query["location"],
    )


def test_rule_version_is_v1_1_and_gate_is_documented():
    assert RULE_VERSION == "rules-v1.1"
    assert MIN_TEXT_OVERLAP == 9


def test_development_split_meets_both_gates():
    data, founds = _load_cases()
    positive = hit = negative = recommended = 0
    for case in data["cases"]:
        if case["split"] != "development":
            continue
        candidates = {c.item_id for c in rank_candidates(_lost(case["query"]), founds)}
        if case["polarity"] == "positive":
            positive += 1
            hit += bool(candidates & set(case["expected_found_labels"]))
        else:
            negative += 1
            recommended += bool(candidates)
    assert positive and negative
    assert hit / positive >= 0.8, f"development recall {hit}/{positive}"
    assert recommended / negative <= 0.2, f"development negatives recommended {recommended}/{negative}"


def test_regression_split_is_reported_honestly():
    """``regression`` is a *seen* set, not an independent unseen test."""
    data, founds = _load_cases()
    positive = hit = negative = recommended = 0
    for case in data["cases"]:
        if case["split"] != "regression":
            continue
        candidates = {c.item_id for c in rank_candidates(_lost(case["query"]), founds)}
        if case["polarity"] == "positive":
            positive += 1
            hit += bool(candidates & set(case["expected_found_labels"]))
        else:
            negative += 1
            recommended += bool(candidates)
    assert hit / positive >= 0.8, f"regression recall {hit}/{positive}"
    assert recommended / negative <= 0.2, f"regression negatives recommended {recommended}/{negative}"
