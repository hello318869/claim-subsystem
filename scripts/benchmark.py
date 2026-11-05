#!/usr/bin/env python3
"""Live performance benchmark: real HTTP backend + real MySQL claim_test.

Self-contained workload:
* creates 1000+ listings in ``claim_test`` with an origin/prefix owned by this run;
* creates one approved claim and 20 messages so the conversation endpoint is real;
* warms up, then runs 3 rounds of 100 requests per endpoint at 20 concurrency;
* endpoints: claim list, conversation read, rule matching;
* gates per-endpoint P95 <= 1000 ms, zero 5xx, zero uncaught exceptions;
* reports status counts, measured data scale, hardware, DB/server pool and rounds;
* removes every row with this run's prefix in a ``finally`` block.

There is no mock/sleep fallback.  The backend must already be running (the test
workflow uses the dedicated port 18080) and must be configured with APP_ENV=test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import socket
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "fixtures"))
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "performance"))

from claimtest.api import Api  # noqa: E402
from claimtest.env import (  # noqa: E402
    TestEnv,
    connect_test_db,
    database_identity,
    load_test_env,
)
from loadgen import (  # noqa: E402
    DEFAULT_CONCURRENCY,
    DEFAULT_P95_LIMIT_MS,
    DEFAULT_REQUESTS_PER_ENDPOINT,
    DEFAULT_ROUNDS,
    DEFAULT_WARMUP,
    MIN_DATASET_SAMPLES,
    evaluate_results,
    run_rounds,
    summarize,
    validate_scale,
)

DEFAULT_OUTPUT = PROJECT_ROOT / "evidence" / "performance-benchmark-v1.0.1.json"
DEFAULT_SERVER_LOG = PROJECT_ROOT / "evidence" / "performance-server-v1.0.1.log"
PREFIX_ROOT = "T-PERF-"
TEST_PORT = 18080


class SetupError(RuntimeError):
    """The benchmark cannot be executed as specified."""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def _memory_info() -> dict[str, Any] | None:
    try:
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {
                "total_bytes": int(status.ullTotalPhys),
                "available_bytes": int(status.ullAvailPhys),
                "source": "GlobalMemoryStatusEx",
            }
    except Exception:  # noqa: BLE001 - Windows-only best effort
        pass
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        return {
            "total_bytes": vm.total,
            "available_bytes": vm.available,
            "source": "psutil",
        }
    except Exception:  # noqa: BLE001
        return None


def _hardware() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "memory": _memory_info(),
        "note": "memory is null only when the platform probe is unavailable",
    }


class PerfDataset:
    """Own a prefixed, origin-tagged slice of claim_test and clean it up."""

    def __init__(self, env: TestEnv) -> None:
        self.env = env
        self.run_id = uuid.uuid4().hex[:8]
        self.prefix = f"{PREFIX_ROOT}{self.run_id}-"
        self.origin = f"perf-{self.run_id}"
        self.claim_id: str | None = None
        self.lost_item_id = f"{self.prefix}L"
        self.target_item_id = f"{self.prefix}T"

    def prepare(self) -> dict[str, Any]:
        from sqlalchemy import insert

        from app.clock import to_db, utcnow
        from app.db import session_scope
        from app.models import Claim, ItemApproval, ListingSnapshot, Message

        now = utcnow()
        claim_id = str(uuid.uuid4())
        self.claim_id = claim_id
        rows = []
        categories = ("bag", "cup", "card", "electronics", "clothing")
        for index in range(1000):
            rows.append(
                {
                    "item_id": f"{self.prefix}F{index:04d}",
                    "kind": "found",
                    "title": f"性能测试拾获物品{index:04d}",
                    "category": categories[index % len(categories)],
                    "occurred_at": to_db(now - timedelta(minutes=index + 5)),
                    "location": "性能测试图书馆",
                    "description": f"性能测试数据 {index:04d} 蓝色水杯 黑色双肩包",
                    "status": "published",
                    "publisher_user_id": "finder",
                    "origin": self.origin,
                    "synced_at": to_db(now),
                }
            )
        rows.append(
            {
                "item_id": self.lost_item_id,
                "kind": "lost",
                "title": "性能测试黑色双肩包",
                "category": "bag",
                "occurred_at": to_db(now - timedelta(days=2)),
                "location": "性能测试图书馆",
                "description": "性能测试丢失：黑色双肩包 蓝色水杯 借书卡",
                "status": "published",
                "publisher_user_id": "alice",
                "origin": self.origin,
                "synced_at": to_db(now),
            }
        )
        rows.append(
            {
                "item_id": self.target_item_id,
                "kind": "found",
                "title": "性能测试黑色双肩包",
                "category": "bag",
                "occurred_at": to_db(now - timedelta(hours=1)),
                "location": "性能测试图书馆",
                "description": "性能测试招领：黑色双肩包 蓝色水杯 借书卡",
                "status": "published",
                "publisher_user_id": "finder",
                "origin": self.origin,
                "synced_at": to_db(now),
            }
        )
        with session_scope() as session:
            session.execute(insert(ListingSnapshot), rows)
            session.add(
                Claim(
                    id=claim_id,
                    item_id=self.target_item_id,
                    applicant_id="alice",
                    finder_id="finder",
                    status="APPROVED",
                    evidence_text="性能测试：包内有蓝色水杯和借书卡",
                    item_number=f"PERF-{self.run_id}",
                    created_at=to_db(now - timedelta(minutes=30)),
                    updated_at=to_db(now),
                    decided_at=to_db(now),
                    approved_at=to_db(now),
                    handover_deadline=to_db(now + timedelta(hours=24)),
                )
            )
            session.add(
                ItemApproval(
                    item_id=self.target_item_id,
                    claim_id=claim_id,
                    approved_at=to_db(now),
                )
            )
            for index in range(20):
                session.add(
                    Message(
                        id=str(uuid.uuid4()),
                        claim_id=claim_id,
                        sender_role="applicant" if index % 2 == 0 else "finder",
                        body=f"性能测试会话消息 {index:02d}",
                        created_at=to_db(
                            now - timedelta(minutes=20) + timedelta(seconds=index)
                        ),
                    )
                )
        return {
            "claim_id": claim_id,
            "lost_item_id": self.lost_item_id,
            "target_item_id": self.target_item_id,
        }

    def measure(self) -> dict[str, int]:
        from sqlalchemy import text

        from app.db import session_scope

        with session_scope() as session:
            counts = {
                "listings": session.execute(
                    text(
                        "SELECT COUNT(*) FROM listing_snapshots "
                        "WHERE item_id LIKE :prefix"
                    ),
                    {"prefix": self.prefix + "%"},
                ).scalar_one(),
                "claims": session.execute(
                    text("SELECT COUNT(*) FROM claims WHERE item_id LIKE :prefix"),
                    {"prefix": self.prefix + "%"},
                ).scalar_one(),
                "messages": session.execute(
                    text("SELECT COUNT(*) FROM messages WHERE claim_id = :claim_id"),
                    {"claim_id": self.claim_id},
                ).scalar_one(),
            }
        return {key: int(value) for key, value in counts.items()}

    def cleanup(self) -> dict[str, Any]:
        from sqlalchemy import delete, select

        from app.db import session_scope
        from app.models import (
            AuditEvent,
            Claim,
            HandoverCode,
            ItemApproval,
            ListingSnapshot,
            Message,
        )

        try:
            with session_scope() as session:
                claim_ids = list(
                    session.execute(
                        select(Claim.id).where(Claim.item_id.like(self.prefix + "%"))
                    ).scalars()
                )
                if claim_ids:
                    session.execute(delete(Message).where(Message.claim_id.in_(claim_ids)))
                    session.execute(
                        delete(HandoverCode).where(HandoverCode.claim_id.in_(claim_ids))
                    )
                    session.execute(
                        delete(AuditEvent).where(AuditEvent.claim_id.in_(claim_ids))
                    )
                    session.execute(delete(Claim).where(Claim.id.in_(claim_ids)))
                session.execute(
                    delete(ItemApproval).where(
                        ItemApproval.item_id.like(self.prefix + "%")
                    )
                )
                session.execute(
                    delete(AuditEvent).where(AuditEvent.item_id.like(self.prefix + "%"))
                )
                session.execute(
                    delete(ListingSnapshot).where(
                        ListingSnapshot.item_id.like(self.prefix + "%")
                    )
                )
            return {"performed": True, "ok": True, "prefix": self.prefix}
        except Exception as exc:  # noqa: BLE001 - record, never hide
            return {
                "performed": True,
                "ok": False,
                "prefix": self.prefix,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }


def _pool_info() -> dict[str, Any]:
    try:
        from app.db import get_engine

        pool = get_engine().pool
        max_overflow = int(getattr(pool, "_max_overflow", 0) or 0)
        return {
            "pool_size": pool.size(),
            "max_overflow": max_overflow,
            "max_connections_per_process": pool.size() + max_overflow,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _server_threads(env: TestEnv) -> int | None:
    conn = connect_test_db(env)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW STATUS LIKE 'Threads_connected'")
            row = cursor.fetchone()
            return int(row[1]) if row else None
    finally:
        conn.close()


class ManagedServer:
    """Own the dedicated 18080 uvicorn process and its log.

    If the server is externally supplied, the caller must provide its log so
    server-side exceptions can still be counted; client 4xx/5xx alone is not
    accepted as the uncaught-exception criterion.
    """

    def __init__(
        self,
        env: TestEnv,
        *,
        base_url: str,
        log_path: Path,
        manage: bool,
    ) -> None:
        self.env = env
        self.base_url = base_url.rstrip("/")
        self.log_path = log_path
        self.manage = manage
        self.process: subprocess.Popen | None = None
        self.log_file = None
        self.offset = 0
        self.port = urlsplit(self.base_url).port or TEST_PORT
        self.pid: int | None = None
        self.released: bool | None = None

    def _port_in_use(self) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.settimeout(1.0)
            return probe.connect_ex(("127.0.0.1", self.port)) == 0
        finally:
            probe.close()

    def _wait_health(self, timeout: float = 40.0) -> None:
        import httpx

        deadline = time.monotonic() + timeout
        last_error: str | None = None
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise SetupError(
                    f"managed uvicorn exited with code {self.process.returncode}"
                )
            try:
                response = httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=1.0)
                if response.status_code == 200:
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.25)
        raise SetupError(f"managed uvicorn not healthy: {last_error}")

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.manage:
            if not self.log_path.is_file():
                raise SetupError(
                    "external backend requires --server-log so server-side exceptions "
                    "can be counted, not inferred only from client status codes"
                )
            self.offset = self.log_path.stat().st_size
            self.released = False
            return

        if self.port != TEST_PORT:
            raise SetupError(
                f"managed test server must use port {TEST_PORT}, got {self.port}"
            )
        if self._port_in_use():
            raise SetupError(
                f"port {self.port} is already in use; refusing to manage a process "
                "owned by someone else"
            )
        self.log_file = self.log_path.open("wb")
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--log-level",
            "info",
        ]
        self.process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=self.env.child_environ(),
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
        )
        self.pid = self.process.pid
        try:
            self._wait_health()
        except Exception:
            self.stop()
            raise
        if self.log_file is not None:
            self.log_file.flush()
        self.offset = self.log_path.stat().st_size
        self.released = False

    def stop(self) -> dict[str, Any]:
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None
        if self.manage:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and self._port_in_use():
                time.sleep(0.1)
            self.released = not self._port_in_use()
        return {
            "managed": self.manage,
            "port": self.port,
            "pid": self.pid,
            "released": self.released,
            "log": str(self.log_path),
        }

    def read_exceptions(self) -> dict[str, Any]:
        try:
            raw = self.log_path.read_bytes()[self.offset :]
        except OSError as exc:
            return {
                "available": False,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                "method": "uvicorn combined stdout/stderr log, offset after startup",
            }
        text = raw.decode("utf-8", "replace")
        tracebacks = text.count("Traceback (most recent call last)")
        asgi = text.count("Exception in ASGI application")
        http_500 = text.count("500 Internal Server Error")
        samples = [
            line.strip()
            for line in text.splitlines()
            if any(
                marker in line
                for marker in ("Traceback (most recent call last)", "Exception in ASGI application", "500 Internal Server Error")
            )
        ][:10]
        return {
            "available": True,
            "method": (
                "uvicorn combined stdout/stderr log; offset taken after startup; "
                "counts Traceback / Exception in ASGI application / 500"
            ),
            "path": str(self.log_path),
            "bytes_read": len(raw),
            "empty_log": len(raw) == 0,
            "tracebacks": tracebacks,
            "asgi_exceptions": asgi,
            "http_500_lines": http_500,
            "samples": samples,
            "passed": len(raw) > 0
            and tracebacks == 0
            and asgi == 0
            and http_500 == 0,
        }


def _endpoint_paths(claim_id: str, lost_item_id: str) -> list[dict[str, str]]:
    claim = quote(claim_id, safe="")
    lost = quote(lost_item_id, safe="")
    return [
        {"name": "claim_list", "path": "/v1/claims?page=1&page_size=20"},
        {"name": "conversation_read", "path": f"/v1/claims/{claim}/messages"},
        {"name": "matching", "path": f"/v1/matches?item_id={lost}"},
    ]


def _preflight(base_url: str, token: str, endpoints: list[dict[str, str]]) -> None:
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    for endpoint in endpoints:
        response = httpx.get(
            base_url.rstrip("/") + endpoint["path"], headers=headers, timeout=20.0
        )
        if response.status_code != 200:
            raise SetupError(
                f"preflight {endpoint['name']} -> {response.status_code}: "
                f"{response.text[:300]}"
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CLAIM_TEST_BASE_URL", "http://127.0.0.1:18080"),
    )
    parser.add_argument("--actor", default="alice")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS_PER_ENDPOINT)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--p95-ms", type=float, default=DEFAULT_P95_LIMIT_MS)
    parser.add_argument("--min-samples", type=int, default=MIN_DATASET_SAMPLES)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--server-log",
        type=Path,
        default=DEFAULT_SERVER_LOG,
        help="uvicorn combined log; server-side exceptions are counted from it",
    )
    parser.add_argument(
        "--manage-server",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="start/stop the dedicated 18080 uvicorn (default: yes)",
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.requests < 100:
        raise SetupError("--requests must be at least 100 per endpoint per round")
    if args.rounds < 3:
        raise SetupError("--rounds must be at least 3")
    if args.concurrency != 20:
        raise SetupError("--concurrency must be exactly 20 for the required workload")
    if args.warmup < 1:
        raise SetupError("--warmup must be at least 1")
    if args.min_samples < 1000:
        raise SetupError("--min-samples must not be below 1000")
    if args.p95_ms > 1000:
        raise SetupError("--p95-ms must not be looser than 1000 ms")
    if not args.output.is_absolute():
        args.output = (PROJECT_ROOT / args.output).resolve()
    if not args.server_log.is_absolute():
        args.server_log = (PROJECT_ROOT / args.server_log).resolve()
    if args.manage_server and (urlsplit(args.base_url).port or TEST_PORT) != TEST_PORT:
        raise SetupError(f"managed backend must use port {TEST_PORT}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate_args(args)
        env = load_test_env()
    except Exception as exc:  # noqa: BLE001
        print(f"setup incomplete: {exc}", file=sys.stderr)
        return 2

    dataset = PerfDataset(env)
    server = ManagedServer(
        env,
        base_url=args.base_url,
        log_path=args.server_log,
        manage=args.manage_server,
    )
    cleanup: dict[str, Any] = {"performed": False}
    server_status: dict[str, Any] = {}
    server_exc: dict[str, Any] = {}
    report: dict[str, Any] | None = None
    exit_code = 2
    try:
        try:
            prepared = dataset.prepare()
            measured = dataset.measure()
            failures = validate_scale(
                {"listings": 1000, "claims": 1, "messages": 20},
                measured,
                minimum=args.min_samples,
            )
            if failures:
                raise SetupError("; ".join(failures))
        except Exception as exc:  # noqa: BLE001
            print(f"setup incomplete: {exc}", file=sys.stderr)
            return 2

        server.start()
        identity = database_identity(env)
        hardware = _hardware()
        pool_info = _pool_info()
        server_threads = _server_threads(env)

        api = Api(args.base_url, timeout=args.timeout)
        try:
            token = api.login(args.actor)
        finally:
            api.close()

        endpoints = _endpoint_paths(prepared["claim_id"], prepared["lost_item_id"])
        _preflight(args.base_url, token, endpoints)

        endpoint_names = [endpoint["name"] for endpoint in endpoints]
        results = asyncio.run(
            run_rounds(
                base_url=args.base_url,
                endpoints=[
                    {"name": endpoint["name"], "url": endpoint["path"]}
                    for endpoint in endpoints
                ],
                token=token,
                rounds=args.rounds,
                requests_per_endpoint=args.requests,
                concurrency=args.concurrency,
                warmup=args.warmup,
                timeout=args.timeout,
            )
        )

        evaluation = evaluate_results(
            results, endpoints=endpoint_names, p95_limit_ms=args.p95_ms
        )
        round_status: dict[str, dict[str, dict[str, int]]] = {}
        for endpoint in endpoint_names:
            round_status[endpoint] = {}
            for round_no in range(1, args.rounds + 1):
                stats = summarize(
                    [
                        row
                        for row in results
                        if row.endpoint == endpoint and row.round_no == round_no
                    ],
                    endpoint,
                )
                round_status[endpoint][str(round_no)] = stats.status_counts

        total_requests = len(results)
        exceptions = sum(1 for row in results if row.status is None)
        five_xx = sum(
            1 for row in results if row.status is not None and row.status >= 500
        )
        passed = bool(evaluation["passed"])
        report = {
            "tool": "benchmark",
            "status": "passed" if passed else "failed",
            "generated_at": _now(),
            "mode": "live-http-real-mysql",
            "mock_used": False,
            "base_url": args.base_url,
            "run_id": dataset.run_id,
            "environment": {
                "database": identity,
                "server_threads_connected_before": server_threads,
                "hardware": hardware,
                "backend_pool": pool_info,
            },
            "dataset": {
                "origin": dataset.origin,
                "prefix": dataset.prefix,
                "measured_counts": measured,
                "declared_counts": {"listings": 1000, "claims": 1, "messages": 20},
                "minimum_samples": args.min_samples,
                "sample_total": sum(measured.values()),
            },
            "connection_pool": {
                "client_concurrency": args.concurrency,
                "client_max_connections": args.concurrency,
                "server_max_connections": identity.get("max_connections"),
                "backend_pool": pool_info,
            },
            "workload": {
                "rounds": args.rounds,
                "warmup_requests_per_endpoint": args.warmup,
                "requests_per_endpoint_per_round": args.requests,
                "concurrency": args.concurrency,
                "total_requests": total_requests,
                "endpoints": endpoints,
            },
            "thresholds": {
                "p95_ms_per_endpoint": args.p95_ms,
                "max_5xx": 0,
                "max_uncaught_exceptions": 0,
                "max_server_tracebacks": 0,
                "min_requests_per_endpoint_per_round": args.requests,
                "min_dataset_samples": args.min_samples,
                "percentile_method": "nearest-rank",
                "warmup_excluded": True,
            },
            "status_counts_per_round": round_status,
            "totals": {
                "requests": total_requests,
                "uncaught_exceptions": exceptions,
                "5xx": five_xx,
            },
            "results": evaluation,
            "conclusion": (
                "PASS: live MySQL dataset measured, per-endpoint P95 within threshold, "
                "0 5xx, 0 uncaught exceptions"
                if passed
                else "FAIL: see results.reasons"
            ),
        }
        exit_code = 0 if passed else 1
    except SetupError as exc:
        print(f"setup incomplete: {exc}", file=sys.stderr)
        exit_code = 2
    except Exception:
        traceback.print_exc()
        exit_code = 2
    finally:
        server_status = server.stop()
        server_exc = server.read_exceptions()
        cleanup = dataset.cleanup()

    if report is not None:
        report["server_process"] = server_status
        report["server_exception_reading"] = server_exc
        report["totals"]["server_tracebacks"] = int(server_exc.get("tracebacks", 0))
        report["totals"]["server_asgi_exceptions"] = int(
            server_exc.get("asgi_exceptions", 0)
        )
        report["cleanup"] = cleanup
        if not cleanup.get("ok", False):
            report["status"] = "failed"
            report["conclusion"] = "FAIL: cleanup of the benchmark prefix failed"
            exit_code = 2
        if not server_exc.get("available", False):
            report["status"] = "failed"
            report["results"]["passed"] = False
            report["results"]["reasons"].append(
                "server-side exception log was not readable"
            )
            report["conclusion"] = (
                "FAIL: server-side exception log was not readable; client status "
                "codes alone are not sufficient"
            )
            exit_code = 2
        elif not server_exc.get("passed", False):
            report["status"] = "failed"
            report["results"]["passed"] = False
            report["results"]["reasons"].append(
                "server log contains traceback/ASGI exception/500"
            )
            report["conclusion"] = (
                "FAIL: server-side log contains traceback/ASGI exception/500"
            )
            exit_code = 1
        elif server_status.get("managed") and not server_status.get("released", False):
            report["status"] = "failed"
            report["results"]["passed"] = False
            report["results"]["reasons"].append("managed test port 18080 was not released")
            report["conclusion"] = "FAIL: managed test port 18080 was not released"
            exit_code = 2
        _write_json(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"benchmark aborted; server={json.dumps(server_status)} "
            f"server_exceptions={json.dumps(server_exc)} cleanup={json.dumps(cleanup)}",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
