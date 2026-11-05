"""Async load-generation primitives for ``scripts/benchmark.py``.

This module performs real HTTP requests against a running backend.  The offline
policy tests only exercise percentile/threshold math; they are not a performance
run and never stand in for one.
"""

from __future__ import annotations

import asyncio
import itertools
import math
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterable, Mapping

import httpx

DEFAULT_P95_LIMIT_MS = 1000.0
DEFAULT_CONCURRENCY = 20
DEFAULT_ROUNDS = 3
DEFAULT_REQUESTS_PER_ENDPOINT = 100
DEFAULT_WARMUP = 10
MIN_DATASET_SAMPLES = 1000


@dataclass(frozen=True)
class Result:
    endpoint: str
    round_no: int
    latency_ms: float
    status: int | None
    error: str | None = None


@dataclass
class EndpointStats:
    endpoint: str
    count: int
    status_counts: dict[str, int]
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    min_ms: float | None
    max_ms: float | None
    exceptions: int
    server_errors: int
    non_2xx: int


@dataclass
class Batch:
    endpoint: str
    round_no: int
    results: list[Result] = field(default_factory=list)


def percentile(values: Iterable[float], p: float) -> float | None:
    """Nearest-rank percentile (no interpolation), matching operation SLIs."""

    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0 < p <= 100:
        raise ValueError("percentile must be in (0, 100]")
    rank = max(1, math.ceil(p / 100.0 * len(ordered)))
    return ordered[rank - 1]


def summarize(results: Iterable[Result], endpoint: str | None = None) -> EndpointStats:
    rows = [row for row in results if endpoint is None or row.endpoint == endpoint]
    name = endpoint or (rows[0].endpoint if rows else "unknown")
    status_counts: dict[str, int] = {}
    latencies: list[float] = []
    exceptions = 0
    server_errors = 0
    non_2xx = 0
    for row in rows:
        status_counts[str(row.status)] = status_counts.get(str(row.status), 0) + 1
        latencies.append(row.latency_ms)
        if row.status is None:
            exceptions += 1
        elif row.status >= 500:
            server_errors += 1
        elif not 200 <= row.status < 300:
            non_2xx += 1
    return EndpointStats(
        endpoint=name,
        count=len(rows),
        status_counts=dict(sorted(status_counts.items())),
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        min_ms=min(latencies) if latencies else None,
        max_ms=max(latencies) if latencies else None,
        exceptions=exceptions,
        server_errors=server_errors,
        non_2xx=non_2xx,
    )


def evaluate_stats(
    stats: EndpointStats, *, p95_limit_ms: float = DEFAULT_P95_LIMIT_MS
) -> list[str]:
    failures: list[str] = []
    if stats.count == 0:
        failures.append("no requests were executed")
        return failures
    if stats.exceptions:
        failures.append(f"{stats.exceptions} uncaught client/transport exception(s)")
    if stats.server_errors:
        failures.append(f"{stats.server_errors} HTTP 5xx response(s)")
    if stats.non_2xx:
        failures.append(f"{stats.non_2xx} non-2xx response(s) (excluding 5xx counted above)")
    if stats.p95_ms is None or stats.p95_ms > p95_limit_ms:
        failures.append(
            f"p95 {stats.p95_ms} ms exceeds {p95_limit_ms} ms"
        )
    return failures


def evaluate_results(
    results: Iterable[Result],
    *,
    endpoints: Iterable[str],
    p95_limit_ms: float = DEFAULT_P95_LIMIT_MS,
) -> dict[str, Any]:
    """Gate each endpoint overall *and* in every round (stricter than required)."""

    rows = list(results)
    report: dict[str, Any] = {"passed": True, "endpoints": {}, "reasons": []}
    for endpoint in endpoints:
        endpoint_rows = [row for row in rows if row.endpoint == endpoint]
        overall = summarize(endpoint_rows, endpoint)
        overall_failures = evaluate_stats(overall, p95_limit_ms=p95_limit_ms)
        rounds: dict[str, Any] = {}
        round_failures: list[str] = []
        for round_no in sorted({row.round_no for row in endpoint_rows}):
            stats = summarize(
                [row for row in endpoint_rows if row.round_no == round_no], endpoint
            )
            failures = evaluate_stats(stats, p95_limit_ms=p95_limit_ms)
            rounds[str(round_no)] = {
                "count": stats.count,
                "status_counts": stats.status_counts,
                "p50_ms": stats.p50_ms,
                "p95_ms": stats.p95_ms,
                "p99_ms": stats.p99_ms,
                "exceptions": stats.exceptions,
                "server_errors": stats.server_errors,
                "non_2xx": stats.non_2xx,
                "passed": not failures,
                "failures": failures,
            }
            if failures:
                round_failures.extend(f"round {round_no}: {item}" for item in failures)
        endpoint_passed = not overall_failures and not round_failures
        report["endpoints"][endpoint] = {
            "count": overall.count,
            "status_counts": overall.status_counts,
            "p50_ms": overall.p50_ms,
            "p95_ms": overall.p95_ms,
            "p99_ms": overall.p99_ms,
            "min_ms": overall.min_ms,
            "max_ms": overall.max_ms,
            "exceptions": overall.exceptions,
            "server_errors": overall.server_errors,
            "non_2xx": overall.non_2xx,
            "rounds": rounds,
            "passed": endpoint_passed,
            "failures": overall_failures + round_failures,
        }
        if not endpoint_passed:
            report["passed"] = False
            report["reasons"].extend(
                f"{endpoint}: {failure}"
                for failure in overall_failures + round_failures
            )
    return report


async def _one_request(
    client: httpx.AsyncClient,
    endpoint: str,
    round_no: int,
    url: str,
    headers: Mapping[str, str],
) -> Result:
    started = perf_counter()
    status: int | None = None
    error: str | None = None
    try:
        response = await client.get(url, headers=dict(headers))
        status = response.status_code
        await response.aread()
    except Exception as exc:  # noqa: BLE001 - every transport failure is data
        error = f"{type(exc).__name__}: {str(exc)[:240]}"
    latency_ms = (perf_counter() - started) * 1000.0
    return Result(
        endpoint=endpoint,
        round_no=round_no,
        latency_ms=latency_ms,
        status=status,
        error=error,
    )


async def run_batch(
    client: httpx.AsyncClient,
    *,
    endpoint: str,
    round_no: int,
    url: str,
    headers: Mapping[str, str],
    count: int,
    concurrency: int,
) -> list[Result]:
    """Run ``count`` requests with at most ``concurrency`` in flight."""

    if count <= 0 or concurrency <= 0:
        raise ValueError("count and concurrency must be positive")
    counter = itertools.count()
    results: list[Result] = []

    async def bounded_worker() -> None:
        while True:
            index = next(counter)
            if index >= count:
                return
            results.append(
                await _one_request(client, endpoint, round_no, url, headers)
            )

    await asyncio.gather(*(bounded_worker() for _ in range(concurrency)))
    return results


async def run_rounds(
    *,
    base_url: str,
    endpoints: Iterable[dict[str, Any]],
    token: str,
    rounds: int = DEFAULT_ROUNDS,
    requests_per_endpoint: int = DEFAULT_REQUESTS_PER_ENDPOINT,
    concurrency: int = DEFAULT_CONCURRENCY,
    warmup: int = DEFAULT_WARMUP,
    timeout: float = 15.0,
) -> list[Result]:
    """Warm up, then run each endpoint in each round and return timestamped results."""

    headers = {"Authorization": f"Bearer {token}"}
    endpoint_list = list(endpoints)
    limits = httpx.Limits(
        max_connections=concurrency, max_keepalive_connections=concurrency
    )
    all_results: list[Result] = []
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
    ) as client:
        for endpoint in endpoint_list:
            for _ in range(warmup):
                await _one_request(
                    client,
                    str(endpoint["name"]),
                    0,
                    str(endpoint["url"]),
                    headers,
                )
        for round_no in range(1, rounds + 1):
            for endpoint in endpoint_list:
                batch = await run_batch(
                    client,
                    endpoint=str(endpoint["name"]),
                    round_no=round_no,
                    url=str(endpoint["url"]),
                    headers=headers,
                    count=requests_per_endpoint,
                    concurrency=concurrency,
                )
                all_results.extend(batch)
    return all_results


def validate_scale(
    declared: Mapping[str, Any],
    measured: Mapping[str, int],
    *,
    minimum: int = MIN_DATASET_SAMPLES,
) -> list[str]:
    """Require a real, measured dataset of at least ``minimum`` samples."""

    failures: list[str] = []
    if not measured:
        failures.append("no measured table counts were provided")
        return failures
    total = sum(int(value) for value in measured.values())
    if total < minimum:
        failures.append(f"measured dataset has {total} rows, need at least {minimum}")
    for key, value in declared.items():
        if key in measured and int(measured[key]) < int(value):
            failures.append(
                f"measured {key}={measured[key]} is below declared {value}"
            )
    return failures
