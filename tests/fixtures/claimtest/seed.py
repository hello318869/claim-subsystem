"""Seed-data adapter.

The backend does not yet publish a seeding module or table schema, so the test
suite never imports application internals and never assumes table names.  A seed
producer (to be agreed with the backend owner) emits a manifest describing real
rows in ``claim_test``.  Tests consume independent scenarios from that manifest.

The manifest is deliberately explicit about:
* the database it seeded (must be ``claim_test``),
* one found listing plus claimant payloads for alice and bob,
* optional mapping for matching-evaluation cases,
* optional benchmark configuration and clock-control SQL.

No manifest is created or guessed by this module.  When none is available the
dependent tests skip with an actionable message instead of fabricating data.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .env import PROJECT_ROOT, TEST_DB_NAME, EnvContractError

DEFAULT_MANIFEST = PROJECT_ROOT / "tests" / "fixtures" / "seed-world.json"
ALLOW_DESTRUCTIVE_ENV = "CLAIM_TEST_ALLOW_DESTRUCTIVE"


class SeedUnavailable(RuntimeError):
    """No usable seed source is configured."""


class SeedContractError(RuntimeError):
    """The seed manifest or seed adapter violates the agreed shape."""


@dataclass(frozen=True)
class ClaimantSpec:
    actor: str
    item_id: object
    item_number: str
    lost_item_id: object | None = None

    def create_payload(self, evidence_text: str) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "evidence_text": evidence_text,
            "item_number": self.item_number,
        }


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    found_id: object
    claimants: Mapping[str, ClaimantSpec]
    found_title: str | None = None

    def claimant(self, actor: str) -> ClaimantSpec:
        try:
            return self.claimants[actor]
        except KeyError as exc:
            raise SeedContractError(
                f"scenario {self.scenario_id!r} has no claimant payload for {actor!r}"
            ) from exc


@dataclass
class World:
    run_id: str
    scenarios: list[Scenario]
    raw: Mapping[str, Any]
    source: str
    database: str | None = None

    def take_scenario(self) -> Scenario:
        if not self.scenarios:
            raise SeedContractError(
                "seed manifest exhausted its scenarios; reseed claim_test and rerun"
            )
        return self.scenarios.pop(0)

    @property
    def matching(self) -> Mapping[str, Any]:
        value = self.raw.get("matching") or {}
        if not isinstance(value, dict):
            raise SeedContractError("manifest.matching must be an object")
        return value

    @property
    def benchmark(self) -> Mapping[str, Any]:
        value = self.raw.get("benchmark") or {}
        if not isinstance(value, dict):
            raise SeedContractError("manifest.benchmark must be an object")
        return value

    @property
    def clock_config(self) -> Mapping[str, Any]:
        value = self.raw.get("clock") or {}
        if not isinstance(value, dict):
            raise SeedContractError("manifest.clock must be an object")
        return value


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SeedContractError(f"{label} must be an object")
    return value


def _read_manifest(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise SeedUnavailable(
            f"seed manifest not found: {path}; set CLAIM_TEST_SEED_MANIFEST, "
            f"CLAIM_TEST_SEED_MODULE or CLAIM_TEST_SEED_COMMAND"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedContractError(f"seed manifest is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise SeedContractError("seed manifest root must be an object")
    return data


def _parse_claimant(actor: str, raw: Any, scenario_id: str) -> ClaimantSpec:
    payload = _require_mapping(raw, f"scenario {scenario_id}.claimants.{actor}")
    missing = [key for key in ("item_id", "item_number") if key not in payload]
    if missing:
        raise SeedContractError(
            f"scenario {scenario_id}.claimants.{actor} misses {', '.join(missing)}"
        )
    item_number = payload["item_number"]
    if not isinstance(item_number, str) or not item_number:
        raise SeedContractError(
            f"scenario {scenario_id}.claimants.{actor}.item_number must be a non-empty string"
        )
    return ClaimantSpec(
        actor=actor,
        item_id=payload["item_id"],
        item_number=item_number,
        lost_item_id=payload.get("lost_item_id"),
    )


def build_world(raw: Mapping[str, Any], *, source: str) -> World:
    database = raw.get("database")
    if database is not None and database != TEST_DB_NAME:
        raise EnvContractError(
            f"seed manifest claims database {database!r}; only {TEST_DB_NAME} is allowed"
        )

    run_id = raw.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise SeedContractError("manifest.run_id must be a non-empty string")

    raw_scenarios = raw.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise SeedContractError("manifest.scenarios must be a non-empty array")

    seen: set[str] = set()
    scenarios: list[Scenario] = []
    for index, item in enumerate(raw_scenarios):
        record = _require_mapping(item, f"scenarios[{index}]")
        scenario_id = record.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise SeedContractError(f"scenarios[{index}].id must be a non-empty string")
        if scenario_id in seen:
            raise SeedContractError(f"duplicate scenario id {scenario_id!r}")
        seen.add(scenario_id)

        if "found_id" not in record:
            raise SeedContractError(f"scenario {scenario_id!r} misses found_id")
        claimants_raw = _require_mapping(
            record.get("claimants"), f"scenario {scenario_id}.claimants"
        )
        missing_actors = [actor for actor in ("alice", "bob") if actor not in claimants_raw]
        if missing_actors:
            raise SeedContractError(
                f"scenario {scenario_id!r} needs claimant payloads for "
                f"{', '.join(missing_actors)} (used by two-party approval tests)"
            )
        claimants = {
            actor: _parse_claimant(actor, payload, scenario_id)
            for actor, payload in claimants_raw.items()
        }
        scenarios.append(
            Scenario(
                scenario_id=scenario_id,
                found_id=record["found_id"],
                claimants=claimants,
                found_title=record.get("found_title"),
            )
        )

    return World(
        run_id=run_id,
        scenarios=scenarios,
        raw=raw,
        source=source,
        database=database,
    )


def _destructive_allowed() -> bool:
    return os.environ.get(ALLOW_DESTRUCTIVE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _run_seed_command(command: str) -> None:
    if not _destructive_allowed():
        raise SeedUnavailable(
            f"CLAIM_TEST_SEED_COMMAND is set but {ALLOW_DESTRUCTIVE_ENV}=1 is not; "
            "refusing to let a seeder modify claim_test unnoticed"
        )
    completed = subprocess.run(
        command,
        shell=True,
        cwd=str(PROJECT_ROOT),
        env=dict(os.environ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip()[-800:]
        raise SeedContractError(
            f"seed command failed with exit {completed.returncode}: {tail}"
        )


def _run_seed_module(module_path: str) -> Mapping[str, Any]:
    if not _destructive_allowed():
        raise SeedUnavailable(
            f"CLAIM_TEST_SEED_MODULE is set but {ALLOW_DESTRUCTIVE_ENV}=1 is not; "
            "refusing to import a module that may reset claim_test"
        )
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # noqa: BLE001 - surfaced with context
        raise SeedContractError(f"cannot import seed module {module_path!r}: {exc}") from exc
    factory = getattr(module, "seed_world", None)
    if not callable(factory):
        raise SeedContractError(
            f"seed module {module_path!r} must expose callable seed_world()"
        )
    try:
        result = factory()
    except Exception as exc:  # noqa: BLE001
        raise SeedContractError(f"seed_world() failed: {exc}") from exc
    if not isinstance(result, dict):
        raise SeedContractError("seed_world() must return the manifest mapping")
    return result


def load_world(*, manifest_path: Path | None = None) -> World:
    """Load a world from the configured seed adapter.

    Order: explicit command, explicit module, explicit manifest path, default
    manifest.  No source is allowed to invent rows.
    """

    configured_path = manifest_path or (
        Path(os.environ["CLAIM_TEST_SEED_MANIFEST"]).expanduser()
        if os.environ.get("CLAIM_TEST_SEED_MANIFEST")
        else DEFAULT_MANIFEST
    )
    if not configured_path.is_absolute():
        configured_path = (PROJECT_ROOT / configured_path).resolve()

    command = os.environ.get("CLAIM_TEST_SEED_COMMAND")
    if command:
        _run_seed_command(command)

    module_path = os.environ.get("CLAIM_TEST_SEED_MODULE")
    if module_path:
        raw = _run_seed_module(module_path)
        return build_world(raw, source=f"module:{module_path}")

    raw = _read_manifest(configured_path)
    return build_world(raw, source=str(configured_path))


def load_manifest_mapping(path: Path) -> Mapping[str, Any]:
    """Read a manifest without requiring test scenarios (used by evaluators)."""

    raw = _read_manifest(path)
    database = raw.get("database")
    if database is not None and database != TEST_DB_NAME:
        raise EnvContractError(
            f"manifest claims database {database!r}; only {TEST_DB_NAME} is allowed"
        )
    return raw


def scenario_pool_size(world: World) -> int:
    return len(world.scenarios)
