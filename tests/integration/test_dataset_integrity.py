"""Offline integrity checks for the frozen matching dataset."""

from __future__ import annotations

import re

import pytest

from claimtest.matching import (
    MIN_DISTRACTORS,
    MIN_NEGATIVES,
    MIN_POSITIVES,
    load_matching_fixture,
    split_counts,
)

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
FROZEN_SHA256 = "443e7e59ed2e887314dc9528d1d2eed5dc7d1565bc92afa56939936047bcef99"


@pytest.mark.offline
def test_dataset_bytes_are_frozen_for_dev_regression():
    fixture = load_matching_fixture()
    assert fixture.sha256 == FROZEN_SHA256
    assert len(fixture.positives) == 40
    assert len(fixture.negatives) == 12
    assert split_counts(fixture) == {
        "development": {"positive": 24, "negative": 7},
        "regression": {"positive": 16, "negative": 5},
    }


@pytest.mark.offline
def test_dataset_has_required_scale_and_split():
    fixture = load_matching_fixture()
    assert len(fixture.positives) >= MIN_POSITIVES
    assert len(fixture.negatives) >= MIN_NEGATIVES
    assert len(fixture.distractors) >= MIN_DISTRACTORS
    counts = split_counts(fixture)
    assert counts["development"]["positive"] > 0
    assert counts["development"]["negative"] > 0
    assert counts["regression"]["positive"] > 0
    assert counts["regression"]["negative"] > 0
    assert fixture.thresholds["positive_top3_recall_min"] >= 0.8
    assert fixture.thresholds["negative_recommended_rate_max"] <= 0.2


@pytest.mark.offline
def test_dataset_has_no_real_pii_or_duplicate_labels():
    fixture = load_matching_fixture()
    blob = fixture.path.read_text(encoding="utf-8")
    assert not PHONE_RE.search(blob)
    assert not EMAIL_RE.search(blob)
    assert not ID_CARD_RE.search(blob)

    labels = [item["label"] for item in fixture.found_records]
    labels += [item["label"] for item in fixture.distractors]
    assert len(labels) == len(set(labels))

    case_ids = [item["id"] for item in fixture.data["cases"]]
    assert len(case_ids) == len(set(case_ids))


@pytest.mark.offline
def test_positive_targets_are_distinct_and_explained():
    fixture = load_matching_fixture()
    targets: list[str] = []
    for case in fixture.positives:
        expected = case["expected_found_labels"]
        assert len(expected) == 1, case["id"]
        targets.append(expected[0])
        assert case["rationale"].strip()
        assert case["query"]["occurred_at"] < next(
            record["occurred_at"]
            for record in fixture.found_records
            if record["label"] == expected[0]
        )
    # One target per physical item; reusing a target would make recall ambiguous.
    assert len(targets) == len(set(targets))


@pytest.mark.offline
def test_negative_cases_declare_no_target():
    fixture = load_matching_fixture()
    for case in fixture.negatives:
        assert case["expected_found_labels"] == []
        assert case["rationale"].strip()


@pytest.mark.offline
def test_fixture_is_read_only_and_metadata_is_frozen():
    fixture = load_matching_fixture()
    data = fixture.data
    assert data["dataset_version"] == "matching-v1"
    assert data["synthetic"] is True
    assert data["provenance"]["generation_rules"]
    assert data["provenance"]["labeling_rules"]
    assert data["provenance"]["limitations"]
    assert data["usage_rules"]
    assert "不得" in " ".join(data["usage_rules"])
