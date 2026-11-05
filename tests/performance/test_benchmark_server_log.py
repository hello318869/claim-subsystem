"""Offline check that server-side exception reading is not a client-only proxy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from claimtest.env import PROJECT_ROOT

pytestmark = pytest.mark.offline


def _load_benchmark():
    path = PROJECT_ROOT / "scripts" / "benchmark.py"
    spec = importlib.util.spec_from_file_location("benchmark_script_v101", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server(module, log_path: Path):
    return module.ManagedServer(
        None,  # read_exceptions does not touch the environment
        base_url="http://127.0.0.1:18080",
        log_path=log_path,
        manage=False,
    )


def test_server_log_counts_tracebacks_and_500(tmp_path):
    module = _load_benchmark()
    path = tmp_path / "uvicorn.log"
    path.write_text(
        "INFO: started server process\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1\n'
        "Exception in ASGI application\n"
        '127.0.0.1 - "GET /v1/claims" 500 Internal Server Error\n',
        encoding="utf-8",
    )
    reading = _server(module, path).read_exceptions()
    assert reading["available"] is True
    assert reading["tracebacks"] == 1
    assert reading["asgi_exceptions"] == 1
    assert reading["http_500_lines"] == 1
    assert reading["passed"] is False
    assert "uvicorn" in reading["method"]


def test_server_log_clean_sample_passes(tmp_path):
    module = _load_benchmark()
    path = tmp_path / "uvicorn-clean.log"
    path.write_text(
        'INFO: 127.0.0.1 - "GET /health" 200 OK\n'
        'INFO: 127.0.0.1 - "GET /v1/claims" 200 OK\n',
        encoding="utf-8",
    )
    reading = _server(module, path).read_exceptions()
    assert reading["available"] is True
    assert reading["tracebacks"] == 0
    assert reading["asgi_exceptions"] == 0
    assert reading["http_500_lines"] == 0
    assert reading["passed"] is True
