"""Settings for the automated test suite.

``APP_ENV=test`` selects ``.env.test`` (the isolated ``claim_test`` database) before
``config.settings`` is imported.  Django's test runner reuses that database instead of creating
a ``test_claim_test`` schema, because the restricted ``claim_app`` account may only manage the
two provisioned databases.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")

from config.settings import *  # noqa: E402,F401,F403
from config.settings import DATABASES  # noqa: E402

DATABASES["default"].setdefault("TEST", {})
DATABASES["default"]["TEST"]["NAME"] = DATABASES["default"]["NAME"]
