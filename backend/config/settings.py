"""Django settings for the campus lost-and-found system.

Configuration comes from ``.env`` (``APP_ENV=dev``) or ``.env.test`` (``APP_ENV=test``) with
process environment overrides.  Only this module reads the files, and no secret is ever printed.

"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"
FRONTEND_BUILD_DIR = FRONTEND_DIR / "dist"
ENVIRONMENT = (os.getenv("APP_ENV", "dev").strip().lower() or "dev")
ENV_FILE = PROJECT_DIR / (".env.test" if ENVIRONMENT == "test" else ".env")


def _read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader matching the format written by scripts/local_mysql.ps1."""
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


_ENV_VALUES = _read_env_file(ENV_FILE)


def env(key: str, default: str | None = None) -> str | None:
    """Environment variable first, then the selected env file, then ``default``."""
    if key in os.environ:
        return os.environ[key]
    return _ENV_VALUES.get(key, default)


def env_flag(key: str, default: bool = False) -> bool:
    value = env(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str) -> list[str]:
    value = env(key) or ""
    return [item.strip() for item in value.split(",") if item.strip()]


# --- Core ---------------------------------------------------------------------------------

SECRET_KEY = env("AUTH_SECRET") or ""
if len(SECRET_KEY) < 16:
    raise RuntimeError(
        f"AUTH_SECRET 缺失或过短（读取自 {ENV_FILE.name} 与进程环境）。\n"
        "请先运行：& '.\\scripts\\local_mysql.ps1' -Action Start"
    )

DEBUG = env_flag("DJANGO_DEBUG", True)
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]", "testserver", *env_list("DJANGO_ALLOWED_HOSTS")]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "users",
    "identity",
    "posts",
    "claims",
    "workflow",
]
AUTH_USER_MODEL = "users.User"

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "common.middleware.SimpleCorsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES: list[dict] = []  # The demo UI is a static bundle; no Django templates are rendered.

APPEND_SLASH = False
DEFAULT_CHARSET = "utf-8"

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Database -----------------------------------------------------------------------------

DATABASE_URL = env("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        f"DATABASE_URL 缺失（读取自 {ENV_FILE.name} 与进程环境）。\n"
        "请先运行：& '.\\scripts\\local_mysql.ps1' -Action Start"
    )


def _database_from_url(url: str) -> dict:
    parts = urlsplit(url)
    backend = parts.scheme.split("+", 1)[0].lower()
    if backend == "sqlite":
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": parts.path.lstrip("/") or str(PROJECT_DIR / "db.sqlite3"),
        }
    if backend != "mysql":
        raise RuntimeError(f"不支持的数据库后端：{parts.scheme}")
    # Django's MySQL backend expects a DB-API named MySQLdb; PyMySQL provides it.
    import pymysql

    pymysql.install_as_MySQLdb()
    query = parse_qs(parts.query)
    return {
        "ENGINE": "django.db.backends.mysql",
        "NAME": parts.path.lstrip("/"),
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "127.0.0.1",
        "PORT": str(parts.port or 3306),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "charset": query.get("charset", ["utf8mb4"])[0],
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }


DATABASES = {"default": _database_from_url(DATABASE_URL)}

# --- Application behaviour ----------------------------------------------------------------

DEMO_MODE = env_flag("DEMO_MODE", False)
DEMO_TOKEN_TTL_HOURS = int(env("DEMO_TOKEN_TTL_HOURS", "24") or 24)
RATE_LIMIT_ENABLED = env_flag("RATE_LIMIT_ENABLED", True)
LOGIN_RATE_LIMIT = 10
BINDING_RATE_LIMIT = 5
RATE_LIMIT_WINDOW_SECONDS = 60
PRIVATE_MEDIA_ROOT = PROJECT_DIR / "tmp" / "private-media"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["common.authentication.BearerAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "common.errors.contract_exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {
        "claims": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
