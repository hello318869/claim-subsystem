"""Offline policy tests for benchmark math and gating.

These tests do not measure the backend and are explicitly not a performance
run.  They prove that the evidence script cannot silently pass a bad sample.
"""

from __future__ import annotations

import pytest

from loadgen import (
    Result,
    evaluate_results,
    evaluate_stats,
    percentile,
    summarize,
    validate_scale,
)


def _result(
    *,
    endpoint: str = "claims",
    round_no: int = 1,
    latency_ms: float = 10.0,
    status: int | None = 200,
    error: str | None = None,
) -> Result:
    return Result(
        endpoint=endpoint,
        round_no=round_no,
        latency_ms=latency_ms,
        status=status,
        error=error,
    )


def test_percentile_uses_nearest_rank():
    assert percentile([], 95) is None
    assert percentile([10], 95) == 10
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 95) == 5
    assert percentile([float(value) for value in range(1, 101)], 95) == 95
    with pytest.raises(ValueError):
        percentile([1], 0)


def test_summarize_reports_status_counts_and_exceptions():
    rows = [
        _result(status=200),
        _result(status=200),
        _result(status=500),
        _result(status=None, error="ConnectError"),
    ]
    stats = summarize(rows, "claims")
    assert stats.count == 4
    assert stats.status_counts == {"200": 2, "500": 1, "None": 1}
    assert stats.exceptions == 1
    assert stats.server_errors == 1
    assert stats.p95_ms is not None


def test_evaluate_passes_clean_sample():
    rows = [_result(latency_ms=10.0) for _ in range(100)]
    report = evaluate_results(rows, endpoints=("claims",), p95_limit_ms=1000)
    assert report["passed"] is True
    assert report["endpoints"]["claims"]["p95_ms"] == 10.0


def test_evaluate_fails_on_p95_5xx_and_exception():
    slow = [_result(latency_ms=5.0) for _ in range(18)] + [
        _result(latency_ms=2000.0) for _ in range(2)
    ]
    report = evaluate_results(slow, endpoints=("claims",), p95_limit_ms=1000)
    assert report["passed"] is False

    five_xx = [_result() for _ in range(19)] + [_result(status=500)]
    report = evaluate_results(five_xx, endpoints=("claims",), p95_limit_ms=1000)
    assert report["passed"] is False

    exception = [_result() for _ in range(19)] + [_result(status=None, error="ReadTimeout")]
    report = evaluate_results(exception, endpoints=("claims",), p95_limit_ms=1000)
    assert report["passed"] is False
    assert "uncaught" in " ".join(report["reasons"])


def test_evaluate_fails_on_non_2xx():
    rows = [_result() for _ in range(19)] + [_result(status=401)]
    report = evaluate_results(rows, endpoints=("claims",), p95_limit_ms=1000)
    assert report["passed"] is False
    assert report["endpoints"]["claims"]["non_2xx"] == 1


def test_evaluate_gates_every_round_not_just_overall():
    rows = [_result(round_no=1, latency_ms=10.0) for _ in range(100)]
    rows += [_result(round_no=2, latency_ms=10.0) for _ in range(100)]
    rows += [_result(round_no=3, latency_ms=2000.0) for _ in range(100)]
    report = evaluate_results(rows, endpoints=("claims",), p95_limit_ms=1000)
    assert report["passed"] is False
    assert report["endpoints"]["claims"]["rounds"]["3"]["passed"] is False
    assert report["endpoints"]["claims"]["p95_ms"] == 2000.0


def test_evaluate_has_no_data_failure():
    report = evaluate_results([], endpoints=("claims",), p95_limit_ms=1000)
    assert report["passed"] is False
    assert "no requests" in report["endpoints"]["claims"]["failures"][0]


def test_validate_scale_requires_measured_rows():
    assert validate_scale({}, {"listings": 1000}) == []
    assert validate_scale({}, {"listings": 999})
    assert validate_scale({}, {})
    assert validate_scale({"listings": 1200}, {"listings": 1100})
    assert validate_scale({"listings": 1000}, {"listings": 1000}) == []


def test_summarize_empty_endpoint_does_not_invent_latency():
    stats = summarize([], "matches")
    assert stats.count == 0
    assert stats.p95_ms is None
    assert "no requests" in evaluate_stats(stats)[0]
