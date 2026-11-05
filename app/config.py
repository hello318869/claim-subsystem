"""Process settings loaded from .env / .env.test with environment overrides.

Only this module reads the environment files. Values are never printed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    auth_secret: str
    handover_secret: str
    demo_mode: bool
    token_ttl_minutes: int = 60
    code_ttl_minutes: int = 30
    handover_deadline_hours: int = 24
    max_resets: int = 2
    max_attempts: int = 5
    cooldown_seconds: int = 60
    pending_ttl_days: int = 7
    match_threshold: int = 40
    match_rule_version: str = "rules-v1.0"
    match_candidate_limit: int = 3
    chat_rate_limit_per_minute: int = 20


def load_settings() -> Settings:
    environment = os.getenv("APP_ENV", "dev").strip().lower() or "dev"
    env_path = ROOT / (".env.test" if environment == "test" else ".env")
    file_values = _read_env_file(env_path)

    def get(key: str, default: str | None = None) -> str | None:
        if key in os.environ:
            return os.environ[key]
        return file_values.get(key, default)

    database_url = get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(f"DATABASE_URL is missing from {env_path.name} and the environment")

    auth_secret = get("AUTH_SECRET") or ""
    if len(auth_secret) < 16:
        raise RuntimeError("AUTH_SECRET is missing or too short")

    handover_secret = get("HANDOVER_SECRET") or f"{auth_secret}:handover-v1"
    demo_mode = (get("DEMO_MODE", "false") or "false").strip().lower() in {"1", "true", "yes", "on"}

    return Settings(
        environment=environment,
        database_url=database_url,
        auth_secret=auth_secret,
        handover_secret=handover_secret,
        demo_mode=demo_mode,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
