"""Environment guard tests: MySQL only, claim_test only, no SQLite fallback."""

from __future__ import annotations

import re

import pytest

from claimtest.env import (
    ENV_TEST_PATH,
    TEST_DB_NAME,
    EnvContractError,
    assert_test_database_url,
    database_name,
    load_test_env,
)


@pytest.mark.offline
def test_env_test_file_is_the_only_configuration_source():
    env = load_test_env()
    assert env.source == ENV_TEST_PATH
    assert database_name(env.database_url) == TEST_DB_NAME
    assert database_name(env.test_database_url) == TEST_DB_NAME
    assert env.demo_mode is True
    # The raw URL must be MySQL, never SQLite/in-memory.
    assert env.test_database_url.startswith(("mysql+pymysql://", "mysql://"))


@pytest.mark.offline
def test_guard_refuses_dev_and_non_test_databases():
    with pytest.raises(EnvContractError):
        assert_test_database_url(
            "mysql+pymysql://u:p@127.0.0.1:33307/claim_dev?charset=utf8mb4",
            label="TEST_DATABASE_URL",
        )
    with pytest.raises(EnvContractError):
        assert_test_database_url(
            "mysql+pymysql://u:p@127.0.0.1:33307/other_db?charset=utf8mb4",
            label="TEST_DATABASE_URL",
        )
    with pytest.raises(EnvContractError):
        assert_test_database_url(
            "sqlite:///./claim_test.db", label="TEST_DATABASE_URL"
        )


def test_isolated_mysql_is_really_mysql(db_identity):
    assert db_identity["database"] == TEST_DB_NAME
    version = str(db_identity["version"])
    assert re.match(r"^8\.0\.", version), version
    assert int(db_identity["port"]) == 33307
