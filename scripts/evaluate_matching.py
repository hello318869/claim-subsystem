#!/usr/bin/env python3
"""Evaluate the frozen matching dataset against the real matching entry.

Two adapters are supported:
* HTTP (default): POST /v1/demo/token then GET /v1/matches?item_id=...;
* in-process module: --entry-module MODULE, exposing match_lost_item(item_id)
  or get_matches(item_id).

The script never edits the fixture.  It records the SHA-256 before and after,
writes a JSON report, and exits 2 on setup gaps (missing manifest/adapter),
1 on a failed gate, 0 on pass.

Dataset labels are never changed to improve a score.  Missing cases, HTTP errors
and misses are recorded verbatim.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import inspect
import json
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "fixtures"))

from claimtest.matching import (  # noqa: E402
    DEFAULT_FIXTURE,
    MatchingFixture,
    load_matching_fixture,
    split_counts,
)
from claimtest.env import EnvContractError  # noqa: E402
from claimtest.seed import DEFAULT_MANIFEST, SeedContractError, load_manifest_mapping  # noqa: E402

DEFAULT_OUTPUT = PROJECT_ROOT / "evidence" / "matching-evaluation-v1.0.1.json"
FOUND_ID_KEYS = ("listing_id", "found_id", "id", "item_id")


@dataclass
class CaseResult:
    case_id: str
    split: str
    polarity: str
    expected_ids: list[str]
    returned_ids: list[str]
    hit: bool | None
    recommended: bool | None
    scores: list[Any]
    error: str | None = None
    rule_version: str | None = None


class SetupError(RuntimeError):
    """The evaluation cannot start with the supplied configuration."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError(f"matching response is not a list/object: {type(payload).__name__}")
    for key in ("items", "matches", "candidates", "results", "recommendations", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested_key in ("items", "matches", "candidates", "recommendations"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return nested
    return []


def _candidate_id(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in FOUND_ID_KEYS:
        value = item.get(key)
        if value is not None:
            return str(value)
    for nested_key in ("found", "item", "listing"):
        nested = item.get(nested_key)
        if isinstance(nested, dict) and nested.get("id") is not None:
            return str(nested["id"])
    return None


def _score(item: Any) -> Any:
    return item.get("score") if isinstance(item, dict) else None


def _rule_version(payload: Any, items: list[Any]) -> str | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("rule_version"), str):
            return payload["rule_version"]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("rule_version"), str):
            return data["rule_version"]
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("rule_version"), str):
            return item["rule_version"]
    return None


def _resolve_mapping(
    fixture: MatchingFixture, manifest: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    matching = manifest.get("matching") or {}
    if not isinstance(matching, dict):
        raise SetupError("manifest.matching must be an object")
    cases_cfg = matching.get("cases") or {}
    if not isinstance(cases_cfg, dict):
        raise SetupError("manifest.matching.cases must be an object")
    found_ids = matching.get("found_ids") or {}
    lost_ids = matching.get("lost_item_ids") or {}
    if not isinstance(found_ids, dict) or not isinstance(lost_ids, dict):
        raise SetupError("manifest.matching.found_ids/lost_item_ids must be objects")

    resolved: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for case in list(fixture.positives) + list(fixture.negatives):
        case_id = str(case["id"])
        cfg = cases_cfg.get(case_id)
        cfg = cfg if isinstance(cfg, dict) else {}
        lost_item_id = cfg.get("lost_item_id", lost_ids.get(case_id))
        if lost_item_id is None:
            errors.append(f"{case_id}: no lost_item_id in manifest.matching")
            continue

        expected_ids: list[str] = []
        explicit = cfg.get("expected_found_ids")
        if isinstance(explicit, list) and explicit:
            expected_ids = [str(value) for value in explicit]
        else:
            for label in case.get("expected_found_labels") or []:
                found_id = found_ids.get(label)
                if found_id is None:
                    errors.append(
                        f"{case_id}: expected label {label!r} has no found_ids entry"
                    )
                else:
                    expected_ids.append(str(found_id))
        if case["polarity"] == "positive" and not expected_ids:
            errors.append(f"{case_id}: positive case has no resolvable expected id")
        resolved[case_id] = {
            "lost_item_id": lost_item_id,
            "expected_ids": expected_ids,
        }
    return resolved, errors


def _http_adapter(base_url: str, actor: str, timeout: float) -> Callable[[Any], Any]:
    from claimtest.api import Api

    api = Api(base_url, timeout=timeout)
    try:
        api.login(actor)
    except Exception as exc:  # noqa: BLE001
        api.close()
        raise SetupError(f"demo login failed for actor {actor!r}: {exc}") from exc

    def invoke(lost_item_id: Any) -> Any:
        response = api.matches(lost_item_id, actor)
        if response.status_code != 200:
            raise RuntimeError(
                f"GET /v1/matches?item_id={lost_item_id} -> {response.status_code}: "
                f"{response.text[:300]}"
            )
        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"matching response is not JSON: {exc}") from exc

    invoke.close = api.close  # type: ignore[attr-defined]
    return invoke


def _module_adapter(module_path: str) -> Callable[[Any], Any]:
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # noqa: BLE001
        raise SetupError(f"cannot import entry module {module_path!r}: {exc}") from exc
    function = getattr(module, "match_lost_item", None) or getattr(
        module, "get_matches", None
    )
    if not callable(function):
        raise SetupError(
            f"entry module {module_path!r} must expose match_lost_item(item_id) "
            "or get_matches(item_id)"
        )

    def invoke(lost_item_id: Any) -> Any:
        result = function(lost_item_id)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        return result

    return invoke


def _run_cases(
    fixture: MatchingFixture,
    resolved: Mapping[str, Mapping[str, Any]],
    invoke: Callable[[Any], Any],
    *,
    top_k: int,
) -> tuple[list[CaseResult], list[str]]:
    results: list[CaseResult] = []
    errors: list[str] = []
    for case in list(fixture.positives) + list(fixture.negatives):
        case_id = str(case["id"])
        mapping = resolved[case_id]
        try:
            payload = invoke(mapping["lost_item_id"])
            items = _extract_items(payload)
            if len(items) > top_k:
                errors.append(
                    f"{case_id}: endpoint returned {len(items)} items, expected Top{top_k}"
                )
            top_items = items[:top_k]
            returned_ids = [
                candidate
                for candidate in (_candidate_id(item) for item in top_items)
                if candidate is not None
            ]
            expected_ids = [str(value) for value in mapping["expected_ids"]]
            result = CaseResult(
                case_id=case_id,
                split=str(case["split"]),
                polarity=str(case["polarity"]),
                expected_ids=expected_ids,
                returned_ids=returned_ids,
                hit=(
                    any(value in returned_ids for value in expected_ids)
                    if case["polarity"] == "positive"
                    else None
                ),
                recommended=(len(top_items) > 0)
                if case["polarity"] == "negative"
                else None,
                scores=[_score(item) for item in top_items],
                error=None,
            )
            version = _rule_version(payload, top_items)
            if version:
                result.rule_version = version
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{case_id}: {type(exc).__name__}: {str(exc)[:300]}")
            results.append(
                CaseResult(
                    case_id=case_id,
                    split=str(case["split"]),
                    polarity=str(case["polarity"]),
                    expected_ids=[str(value) for value in mapping["expected_ids"]],
                    returned_ids=[],
                    hit=False if case["polarity"] == "positive" else None,
                    recommended=None if case["polarity"] == "negative" else None,
                    scores=[],
                    error=f"{type(exc).__name__}: {str(exc)[:300]}",
                )
            )
    return results, errors


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metrics(results: list[CaseResult]) -> dict[str, Any]:
    positives = [row for row in results if row.polarity == "positive"]
    negatives = [row for row in results if row.polarity == "negative"]
    hits = sum(1 for row in positives if row.hit is True)
    recommended = sum(1 for row in negatives if row.recommended is True)
    negative_with_positive_score = 0
    for row in negatives:
        if row.recommended and any(
            isinstance(score, (int, float)) and score > 0 for score in row.scores
        ):
            negative_with_positive_score += 1
    return {
        "positive_count": len(positives),
        "positive_hits": hits,
        "positive_topk_recall": _rate(hits, len(positives)),
        "negative_count": len(negatives),
        "negative_recommended": recommended,
        "negative_recommended_rate": _rate(recommended, len(negatives)),
        "negative_with_score_gt_0": negative_with_positive_score,
        "negative_positive_score_rate": _rate(
            negative_with_positive_score, len(negatives)
        ),
    }


def _split_metrics(results: list[CaseResult]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for split in sorted({row.split for row in results}):
        output[split] = _metrics([row for row in results if row.split == split])
    return output


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def _validate_only(fixture: MatchingFixture) -> dict[str, Any]:
    return {
        "status": "validated",
        "dataset_version": fixture.dataset_version,
        "fixture": str(fixture.path),
        "fixture_sha256": fixture.sha256,
        "counts": fixture.data.get("counts"),
        "split_counts": split_counts(fixture),
        "thresholds": fixture.thresholds,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(os.environ.get("CLAIM_TEST_SEED_MANIFEST", str(DEFAULT_MANIFEST))),
        help="seed manifest containing matching.lost_item_ids/found_ids (or matching.cases)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CLAIM_TEST_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--actor", default="alice")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument(
        "--entry-module",
        default=os.environ.get("MATCHING_ENTRY_MODULE", ""),
        help="in-process adapter module instead of HTTP",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-version", default="v1.0.1")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.top_k != 3:
        print("warning: the frozen thresholds target Top3", file=sys.stderr)
    if not args.fixture.is_absolute():
        args.fixture = (PROJECT_ROOT / args.fixture).resolve()
    if not args.manifest.is_absolute():
        args.manifest = (PROJECT_ROOT / args.manifest).resolve()
    if not args.output.is_absolute():
        args.output = (PROJECT_ROOT / args.output).resolve()

    before = _sha256(args.fixture)
    try:
        fixture = load_matching_fixture(args.fixture)
    except Exception as exc:  # noqa: BLE001
        print(f"fixture error: {exc}", file=sys.stderr)
        return 2
    if fixture.sha256 != before:
        print("fixture changed while loading; abort", file=sys.stderr)
        return 2
    if args.validate_only:
        print(json.dumps(_validate_only(fixture), ensure_ascii=False, indent=2))
        return 0

    if not args.manifest.is_file():
        print(
            f"setup incomplete: seed manifest not found at {args.manifest}. "
            "Provide matching.lost_item_ids/found_ids from a claim_test seed, or "
            "run --validate-only for dataset checks.",
            file=sys.stderr,
        )
        return 2
    try:
        manifest = load_manifest_mapping(args.manifest)
        resolved, mapping_errors = _resolve_mapping(fixture, manifest)
    except (SetupError, SeedContractError, EnvContractError, OSError, json.JSONDecodeError) as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    if mapping_errors:
        print("setup incomplete:\n- " + "\n- ".join(mapping_errors), file=sys.stderr)
        return 2

    invoke: Callable[[Any], Any]
    adapter_info: dict[str, Any]
    if args.entry_module:
        try:
            invoke = _module_adapter(args.entry_module)
        except SetupError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        adapter_info = {"mode": "module", "module": args.entry_module}
    else:
        try:
            invoke = _http_adapter(args.base_url, args.actor, args.timeout)
        except SetupError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        adapter_info = {
            "mode": "http",
            "base_url": args.base_url,
            "actor": args.actor,
        }

    try:
        results, execution_errors = _run_cases(
            fixture, resolved, invoke, top_k=args.top_k
        )
    finally:
        close = getattr(invoke, "close", None)
        if callable(close):
            close()

    overall = _metrics(results)
    splits = _split_metrics(results)
    thresholds = fixture.thresholds
    rule_versions = sorted(
        {
            getattr(row, "rule_version")
            for row in results
            if getattr(row, "rule_version", None)
        }
    )
    reasons: list[str] = []
    recall_target = float(thresholds["positive_top3_recall_min"])
    negative_target = float(thresholds["negative_recommended_rate_max"])
    if overall["positive_topk_recall"] is None or overall["positive_topk_recall"] < recall_target:
        reasons.append(
            f"Top{args.top_k} recall {overall['positive_topk_recall']} < {recall_target}"
        )
    if overall["negative_recommended_rate"] is None or overall["negative_recommended_rate"] > negative_target:
        reasons.append(
            "negative recommended rate "
            f"{overall['negative_recommended_rate']} > {negative_target}"
        )
    if execution_errors:
        reasons.append(f"{len(execution_errors)} case execution error(s)")
    if not rule_versions:
        reasons.append("no rule_version returned by the matching entry")
    after = _sha256(args.fixture)
    if after != before:
        reasons.append("fixture SHA-256 changed during evaluation (labels must be immutable)")

    positive_misses = [
        {
            "case_id": row.case_id,
            "split": row.split,
            "expected_ids": row.expected_ids,
            "returned_ids": row.returned_ids,
            "scores": row.scores,
            "error": row.error,
        }
        for row in results
        if row.polarity == "positive" and row.hit is not True
    ]
    negative_recommended = [
        {
            "case_id": row.case_id,
            "split": row.split,
            "returned_ids": row.returned_ids,
            "scores": row.scores,
            "error": row.error,
        }
        for row in results
        if row.polarity == "negative" and row.recommended is True
    ]

    report = {
        "tool": "evaluate_matching",
        "evidence_version": args.evidence_version,
        "status": "passed" if not reasons else "failed",
        "generated_at": _now(),
        "fixture": str(args.fixture),
        "fixture_sha256_before": before,
        "fixture_sha256_after": after,
        "dataset_version": fixture.dataset_version,
        "adapter": adapter_info,
        "top_k": args.top_k,
        "counts": fixture.data.get("counts"),
        "split_counts": split_counts(fixture),
        "metrics": overall,
        "split_metrics": splits,
        "thresholds": thresholds,
        "gate": {"passed": not reasons, "reasons": reasons},
        "rule_versions": rule_versions,
        "failures": {
            "positive_misses": positive_misses,
            "negative_recommended": negative_recommended,
            "execution_errors": execution_errors,
        },
        "privacy": "synthetic dataset; no real personal data",
        "evaluation_scope": {
            "development": "used for rule/gate selection",
            "regression": "已见合成回归集 (seen synthetic regression set)",
            "generalization_claim": (
                "not an unseen/generalization accuracy; both splits are synthetic and "
                "the regression split has been reviewed"
            ),
        },
        "notes": [
            "Labels are frozen; the script only reads the fixture.",
            "Negative recommendation is counted as any non-empty Top3; "
            "the score>0 rate is reported separately.",
            "已见合成回归集：不得将本报告数值表述为未见数据的泛化准确率。",
        ],
    }
    _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception:  # noqa: BLE001 - do not hide a traceback in evidence tooling
        traceback.print_exc()
        raise SystemExit(2)
