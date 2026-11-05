"""Environment loading and hard guards for the isolated test database.

Rules enforced here:
* Test configuration is read from this project's ``.env.test`` only.
* Both ``DATABASE_URL`` and ``TEST_DATABASE_URL`` must name ``claim_test``.
* The real ``.env`` file and any other database are never consulted.
* Credentials are never printed or included in exception messages.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlsplit

TEST_DB_NAME = "claim_test"
FORBIDDEN_DB_NAMES = {"claim_dev"}
REQUIRED_KEYS = ("DATABASE_URL", "TEST_DATABASE_URL", "AUTH_SECRET", "DEMO_MODE")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_TEST_PATH = PROJECT_ROOT / ".env.test"


class EnvContractError(RuntimeError):
    """The test environment file violates the project-wide test contract."""


@dataclass(frozen=True)
class TestEnv:
    database_url: str = field(repr=False)
    test_database_url: str = field(repr=False)
    auth_secret: str = field(repr=False)
    demo_mode: bool
    source: Path

    def child_environ(self) -> dict[str, str]:
        """Environment for a backend process started by the tests."""

        env = dict(os.environ)
        env.update(
            {
                "APP_ENV": "test",
                "DATABASE_URL": self.database_url,
                "TEST_DATABASE_URL": self.test_database_url,
                "AUTH_SECRET": self.auth_secret,
                "DEMO_MODE": "true" if self.demo_mode else "false",
            }
        )
        return env

    def mysql_dsn(self) -> dict[str, object]:
        """Connection arguments for the test database, with the guard re-applied."""

        return mysql_dsn(self.test_database_url, label="TEST_DATABASE_URL")


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise EnvContractError(f"Required test environment file is missing: {path}")
    values: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise EnvContractError(f"{path.name}:{lineno} is not a KEY=VALUE line")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            raise EnvContractError(f"{path.name}:{lineno} has an empty key")
        values[key] = value
    missing = [key for key in REQUIRED_KEYS if not values.get(key)]
    if missing:
        raise EnvContractError(
            f"{path.name} is missing required keys: {', '.join(missing)}"
        )
    return values


def database_name(url: str) -> str:
    """Return the database name from a SQLAlchemy-style MySQL URL."""

    try:
        parts = urlsplit(url)
    except ValueError as exc:  # pragma: no cover - malformed URL
        raise EnvContractError("Database URL cannot be parsed") from exc
    if parts.scheme not in {"mysql+pymysql", "mysql"}:
        raise EnvContractError(
            "Only MySQL URLs are accepted by this test suite; "
            f"got scheme {parts.scheme!r}"
        )
    name = parts.path.lstrip("/")
    if not name or "/" in name:
        raise EnvContractError("Database URL must contain exactly one database name")
    return name


def assert_test_database_url(url: str, *, label: str) -> str:
    """Validate one URL and return its database name, refusing anything but claim_test."""

    name = database_name(url)
    if name in FORBIDDEN_DB_NAMES:
        raise EnvContractError(
            f"{label} points at forbidden database {name!r}; tests may only use {TEST_DB_NAME}"
        )
    if name != TEST_DB_NAME:
        raise EnvContractError(
            f"{label} must point at {TEST_DB_NAME}, got {name!r}; refusing to run"
        )
    return name


def mysql_dsn(url: str, *, label: str = "database URL") -> dict[str, object]:
    """Build PyMySQL connection arguments without ever logging the password."""

    assert_test_database_url(url, label=label)
    parts = urlsplit(url)
    query = {}
    for chunk in parts.query.split("&"):
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        query[key] = unquote(value)
    return {
        "host": parts.hostname or "127.0.0.1",
        "port": parts.port or 3306,
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": parts.path.lstrip("/"),
        "charset": query.get("charset", "utf8mb4"),
        "connect_timeout": 5,
        "read_timeout": 15,
        "write_timeout": 15,
        "autocommit": True,
    }


def load_test_env(path: Path | None = None) -> TestEnv:
    """Read, validate and export the only permitted test environment."""

    env_path = path or ENV_TEST_PATH
    values = _parse_env_file(env_path)

    dbs = {
        "DATABASE_URL": assert_test_database_url(
            values["DATABASE_URL"], label="DATABASE_URL"
        ),
        "TEST_DATABASE_URL": assert_test_database_url(
            values["TEST_DATABASE_URL"], label="TEST_DATABASE_URL"
        ),
    }
    if len(set(dbs.values())) != 1:
        raise EnvContractError("Both database URLs must target the same test database")

    demo_mode = values["DEMO_MODE"].strip().lower()
    if demo_mode not in {"true", "1", "yes"}:
        raise EnvContractError("DEMO_MODE must be true for the identity demonstration")

    # Force the validated values into the test process so an inherited shell
    # environment can never redirect the app or the tests to claim_dev.
    os.environ.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": values["DATABASE_URL"],
            "TEST_DATABASE_URL": values["TEST_DATABASE_URL"],
            "AUTH_SECRET": values["AUTH_SECRET"],
            "DEMO_MODE": values["DEMO_MODE"],
        }
    )

    return TestEnv(
        database_url=values["DATABASE_URL"],
        test_database_url=values["TEST_DATABASE_URL"],
        auth_secret=values["AUTH_SECRET"],
        demo_mode=True,
        source=env_path,
    )


def connect_test_db(env: TestEnv):
    """Open a PyMySQL connection and assert the server-side current database."""

    import pymysql

    dsn = env.mysql_dsn()
    conn = pymysql.connect(**dsn)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DATABASE()")
            row = cursor.fetchone()
    except Exception:
        conn.close()
        raise
    current = row[0] if row else None
    if current != TEST_DB_NAME:
        conn.close()
        raise EnvContractError(
            f"Connected database is {current!r}, expected {TEST_DB_NAME!r}; refusing to continue"
        )
    return conn


def database_identity(env: TestEnv) -> dict[str, object]:
    """Small, non-secret identity snapshot for evidence files."""

    conn = connect_test_db(env)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT VERSION(), DATABASE(), CURRENT_USER(), @@port, "
                "@@max_connections, @@innodb_buffer_pool_size, "
                "@@transaction_isolation"
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    keys = (
        "version",
        "database",
        "current_user",
        "port",
        "max_connections",
        "innodb_buffer_pool_size",
        "transaction_isolation",
    )
    return {
        key: (value.decode() if isinstance(value, bytes) else value)
        for key, value in zip(keys, row)
    }


def env_file_fingerprint(env: TestEnv) -> Mapping[str, str]:
    """Report non-secret facts about the environment file for evidence."""

    return {
        "file": env.source.name,
        "database": TEST_DB_NAME,
        "demo_mode": "true" if env.demo_mode else "false",
        "has_auth_secret": "yes" if env.auth_secret else "no",
    }
