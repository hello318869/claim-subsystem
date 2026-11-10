#!/usr/bin/env python
"""Django management entry point for the campus claim subsystem (C)."""

from __future__ import annotations

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - only on a broken install
        raise ImportError(
            "Django 未安装。请在项目根目录运行 python -m pip install -r backend/requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
