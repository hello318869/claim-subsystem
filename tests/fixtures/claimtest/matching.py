"""Loading and validating the labelled synthetic matching dataset.

The fixture is frozen test data, not a rules-development playground: the
evaluation script only reads it and records its SHA-256 before/after the run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .env import PROJECT_ROOT

DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "matching-v1.json"
MIN_POSITIVES = 30
MIN_NEGATIVES = 10
MIN_DISTRACTORS = 10
REQUIRED_RECORD_FIELDS = ("title", "category", "description", "occurred_at", "location")
POSITIVE = "positive"
NEGATIVE = "negative"


class MatchingFixtureError(RuntimeError):
    """The matching dataset does not meet its documented contract."""


@dataclass(frozen=True)
class MatchingFixture:
    path: Path
    sha256: str
    data: Mapping[str, Any]
    positives: tuple[Mapping[str, Any], ...]
    negatives: tuple[Mapping[str, Any], ...]
    found_records: tuple[Mapping[str, Any], ...]
    distractors: tuple[Mapping[str, Any], ...]

    @property
    def dataset_version(self) -> str:
        return str(self.data.get("dataset_version") or self.data.get("version") or "")

    @property
    def thresholds(self) -> Mapping[str, Any]:
        value = self.data.get("thresholds") or {}
        return value if isinstance(value, dict) else {}


def _records(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise MatchingFixtureError(f"{label} must be an array")
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MatchingFixtureError(f"{label}[{index}] must be an object")
        result.append(item)
    return result


def _check_record(record: Mapping[str, Any], label: str) -> None:
    for key in REQUIRED_RECORD_FIELDS:
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise MatchingFixtureError(f"{label}.{key} must be a non-empty string")
    try:
        datetime.fromisoformat(str(record["occurred_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise MatchingFixtureError(
            f"{label}.occurred_at is not ISO-8601: {record['occurred_at']!r}"
        ) from exc


def validate_fixture(data: Mapping[str, Any]) -> None:
    if not isinstance(data, dict):
        raise MatchingFixtureError("fixture root must be an object")

    dataset_version = data.get("dataset_version") or data.get("version")
    if not isinstance(dataset_version, str) or not dataset_version:
        raise MatchingFixtureError("dataset_version must be a non-empty string")

    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        raise MatchingFixtureError("provenance object is required")
    for key in ("generation_rules", "labeling_rules", "limitations"):
        value = provenance.get(key)
        if not isinstance(value, list) or not value:
            raise MatchingFixtureError(f"provenance.{key} must be a non-empty array")
    if not isinstance(provenance.get("split_rule"), str) or not provenance["split_rule"].strip():
        raise MatchingFixtureError("provenance.split_rule must be a non-empty string")

    thresholds = data.get("thresholds")
    if not isinstance(thresholds, dict):
        raise MatchingFixtureError("thresholds object is required")
    recall = thresholds.get("positive_top3_recall_min")
    negative_rate = thresholds.get("negative_recommended_rate_max")
    if not isinstance(recall, (int, float)) or not 0 <= float(recall) <= 1:
        raise MatchingFixtureError("thresholds.positive_top3_recall_min must be in [0,1]")
    if not isinstance(negative_rate, (int, float)) or not 0 <= float(negative_rate) <= 1:
        raise MatchingFixtureError(
            "thresholds.negative_recommended_rate_max must be in [0,1]"
        )
    if float(recall) < 0.8:
        raise MatchingFixtureError("top-3 recall target must not be below 0.8")
    if float(negative_rate) > 0.2:
        raise MatchingFixtureError("negative recommendation ceiling must not exceed 0.2")

    found = _records(data.get("found_records"), "found_records")
    distractors = _records(data.get("distractors"), "distractors")
    cases = _records(data.get("cases"), "cases")

    labels: set[str] = set()
    for index, record in enumerate(found):
        label = record.get("label")
        if not isinstance(label, str) or not label:
            raise MatchingFixtureError(f"found_records[{index}].label missing")
        if label in labels:
            raise MatchingFixtureError(f"duplicate found label {label!r}")
        labels.add(label)
        _check_record(record, f"found_records[{label}]")

    distractor_labels: set[str] = set()
    for index, record in enumerate(distractors):
        label = record.get("label")
        if not isinstance(label, str) or not label:
            raise MatchingFixtureError(f"distractors[{index}].label missing")
        if label in labels or label in distractor_labels:
            raise MatchingFixtureError(f"duplicate label {label!r} across records")
        distractor_labels.add(label)
        _check_record(record, f"distractors[{label}]")

    case_ids: set[str] = set()
    positives = 0
    negatives = 0
    split_counts: dict[str, dict[str, int]] = {}
    for index, case in enumerate(cases):
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise MatchingFixtureError(f"cases[{index}].id missing")
        if case_id in case_ids:
            raise MatchingFixtureError(f"duplicate case id {case_id!r}")
        case_ids.add(case_id)

        split = case.get("split")
        if split not in {"development", "regression"}:
            raise MatchingFixtureError(
                f"case {case_id}.split must be development or regression"
            )
        polarity = case.get("polarity")
        if polarity not in {POSITIVE, NEGATIVE}:
            raise MatchingFixtureError(
                f"case {case_id}.polarity must be positive or negative"
            )
        query = case.get("query")
        if not isinstance(query, dict):
            raise MatchingFixtureError(f"case {case_id}.query must be an object")
        _check_record(query, f"case {case_id}.query")

        if not isinstance(case.get("rationale"), str) or not case["rationale"].strip():
            raise MatchingFixtureError(f"case {case_id}.rationale must be non-empty")

        split_counts.setdefault(split, {"positive": 0, "negative": 0})[polarity] += 1

        expected = case.get("expected_found_labels")
        if polarity == POSITIVE:
            positives += 1
            if not isinstance(expected, list) or not expected:
                raise MatchingFixtureError(
                    f"positive case {case_id} needs expected_found_labels"
                )
            for label in expected:
                if label not in labels:
                    raise MatchingFixtureError(
                        f"case {case_id} expects unknown found label {label!r}"
                    )
        else:
            negatives += 1
            if expected not in (None, []):
                raise MatchingFixtureError(
                    f"negative case {case_id} must not declare expected found labels"
                )

    if positives < MIN_POSITIVES:
        raise MatchingFixtureError(
            f"need at least {MIN_POSITIVES} positive cases, found {positives}"
        )
    if negatives < MIN_NEGATIVES:
        raise MatchingFixtureError(
            f"need at least {MIN_NEGATIVES} negative cases, found {negatives}"
        )
    if len(distractors) < MIN_DISTRACTORS:
        raise MatchingFixtureError(
            f"need at least {MIN_DISTRACTORS} distractor records, found {len(distractors)}"
        )
    for split in ("development", "regression"):
        counts = split_counts.get(split)
        if not counts or counts["positive"] == 0 or counts["negative"] == 0:
            raise MatchingFixtureError(
                f"split {split!r} must contain both positive and negative cases"
            )

    declared = data.get("counts")
    if declared is not None:
        expected_counts = {
            "positive": positives,
            "negative": negatives,
            "distractors": len(distractors),
            "found_records": len(found),
        }
        for key, value in expected_counts.items():
            if declared.get(key) != value:
                raise MatchingFixtureError(
                    f"declared counts.{key}={declared.get(key)!r} but file has {value}"
                )


def load_matching_fixture(path: Path | None = None) -> MatchingFixture:
    fixture_path = path or DEFAULT_FIXTURE
    raw_bytes = fixture_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MatchingFixtureError(f"fixture is not valid JSON: {fixture_path}") from exc
    validate_fixture(data)

    cases = _records(data.get("cases"), "cases")
    positives = tuple(case for case in cases if case.get("polarity") == POSITIVE)
    negatives = tuple(case for case in cases if case.get("polarity") == NEGATIVE)
    return MatchingFixture(
        path=fixture_path,
        sha256=sha256,
        data=data,
        positives=positives,
        negatives=negatives,
        found_records=tuple(_records(data.get("found_records"), "found_records")),
        distractors=tuple(_records(data.get("distractors"), "distractors")),
    )


def split_counts(fixture: MatchingFixture) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for case in fixture.data.get("cases", []):
        split = str(case["split"])
        polarity = str(case["polarity"])
        counts.setdefault(split, {"positive": 0, "negative": 0})[polarity] += 1
    return counts
