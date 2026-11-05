"""Session fixtures for the HTTP black-box suite.

Design rules:
* Tests talk to a real backend over HTTP; SQLite/in-memory stand-ins are refused.
* Test configuration comes only from ``.env.test`` and must name ``claim_test``.
* Seed data is declared by an external manifest/module; no test invents DB rows.
* A server may be supplied via ``CLAIM_TEST_BASE_URL`` or started by pytest via
  ``CLAIM_TEST_APP`` (uvicorn import string) using the validated test env.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterator, Mapping

import pytest

from claimtest.api import Api
from claimtest.clock import ClockSeam
from claimtest.dbtools import TestDatabase
from claimtest.env import (
    PROJECT_ROOT,
    TEST_DB_NAME,
    EnvContractError,
    TestEnv,
    database_identity,
    load_test_env,
)
from claimtest.seed import SeedContractError, SeedUnavailable, World, load_world

ACTORS = ("alice", "bob", "finder", "outsider")
DEFAULT_MIN_SCENARIOS = int(os.environ.get("CLAIM_TEST_MIN_SCENARIOS", "120"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: HTTP black-box test against the real backend"
    )
    config.addinivalue_line(
        "markers", "performance_policy: offline checks of benchmark methodology"
    )
    config.addinivalue_line(
        "markers", "contract_pending: behavior awaits the frozen api-contract.md"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/integration/" in path:
            item.add_marker(pytest.mark.integration)
        if "/performance/" in path:
            item.add_marker(pytest.mark.performance_policy)
        if "/test_regression_" in path:
            item.add_marker(pytest.mark.regression_v1_0_1)


@pytest.fixture(scope="session")
def test_env() -> TestEnv:
    try:
        return load_test_env()
    except EnvContractError as exc:
        pytest.fail(f"Test environment guard failed: {exc}", pytrace=False)


def _port_from_url(url: str, default: int) -> int:
    parsed = urllib.parse.urlsplit(url)
    return parsed.port or default


def _wait_for_http(url: str, process: subprocess.Popen | None, timeout: float = 40.0) -> None:
    import httpx

    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"backend exited with code {process.returncode}")
        try:
            # Any HTTP response means the ASGI stack is accepting requests.
            httpx.get(url, timeout=1.0)
            return
        except Exception as exc:  # noqa: BLE001 - readiness probe
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.2)
    raise TimeoutError(f"backend did not become ready at {url}: {last_error}")


@pytest.fixture(scope="session")
def base_url(test_env: TestEnv, tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    configured_url = os.environ.get("CLAIM_TEST_BASE_URL", "").strip()
    app = os.environ.get("CLAIM_TEST_APP", "").strip()

    if configured_url and not app:
        try:
            _wait_for_http(configured_url, None, timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(
                f"backend not reachable at {configured_url} ({exc}); start it with "
                ".env.test/APP_ENV=test or set CLAIM_TEST_APP=app.main:app for auto-start",
                allow_module_level=False,
            )
        yield configured_url.rstrip("/")
        return

    # Prefer a dedicated pytest-managed port so a developer server is untouched.
    port = _port_from_url(configured_url, 18080) if configured_url else 18080
    url = configured_url or f"http://127.0.0.1:{port}"
    app = app or "app.main:app"
    log_dir = tmp_path_factory.mktemp("backend-log")
    log_path = log_dir / "uvicorn.log"
    log_file = log_path.open("wb")
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        app,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=test_env.child_environ(),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_http(url, process)
    except Exception as exc:  # noqa: BLE001
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log_file.close()
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-2500:]
        pytest.fail(
            f"pytest could not start backend {app!r} at {url}: {exc}\n"
            f"--- uvicorn tail ---\n{tail}",
            pytrace=False,
        )
    try:
        yield url.rstrip("/")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        log_file.close()


@pytest.fixture(scope="session")
def api(base_url: str) -> Iterator[Api]:
    client = Api(base_url)
    try:
        for actor in ACTORS:
            try:
                client.login(actor)
            except Exception as exc:  # noqa: BLE001 - report contract failure
                pytest.fail(
                    f"demo identity for actor {actor!r} is not usable: {exc}",
                    pytrace=False,
                )
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def tokens(api: Api) -> dict[str, str]:
    return {actor: api.token(actor) for actor in ACTORS}


@pytest.fixture(scope="session")
def db_identity(test_env: TestEnv) -> Mapping[str, Any]:
    try:
        return database_identity(test_env)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"isolated MySQL claim_test is not reachable: {exc}")


@pytest.fixture(scope="session")
def world(test_env: TestEnv, db_identity: Mapping[str, Any]) -> World:
    try:
        loaded = load_world()
    except SeedUnavailable as exc:
        pytest.skip(str(exc), allow_module_level=False)
    except (SeedContractError, EnvContractError) as exc:
        pytest.fail(f"seed contract failed: {exc}", pytrace=False)

    if loaded.database is None:
        pytest.fail(
            "seed manifest must declare \"database\": \"claim_test\" so tests can "
            "prove they are not running against another schema",
            pytrace=False,
        )
    if loaded.database != TEST_DB_NAME:
        pytest.fail(
            f"seed manifest targets {loaded.database!r}, not {TEST_DB_NAME}",
            pytrace=False,
        )
    if len(loaded.scenarios) < DEFAULT_MIN_SCENARIOS:
        pytest.fail(
            f"seed manifest has {len(loaded.scenarios)} independent scenarios; this "
            f"suite needs at least {DEFAULT_MIN_SCENARIOS} fresh scenarios "
            "(set CLAIM_TEST_MIN_SCENARIOS only if the test selection is smaller). "
            "Reseed claim_test with a larger scenario pool.",
            pytrace=False,
        )
    return loaded


@pytest.fixture()
def scenario(world: World) -> Any:
    try:
        return world.take_scenario()
    except SeedContractError as exc:
        pytest.fail(str(exc), pytrace=False)


@pytest.fixture(scope="session")
def clock(world: World, test_env: TestEnv) -> ClockSeam:
    return ClockSeam(world.clock_config, test_env)


@pytest.fixture(scope="session")
def db_tools(test_env: TestEnv) -> TestDatabase:
    return TestDatabase(test_env)
