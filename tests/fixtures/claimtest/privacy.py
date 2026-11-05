"""Privacy assertions shared by black-box integration tests.

The project contract says public DTOs must not expose ``user_id``, publisher
identities or any real-identity mapping.  We assert this structurally (forbidden
keys anywhere in the JSON) instead of guessing numeric user identifiers.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

# Exact normalized key names that must never appear in a public DTO, a claim
# view, a message DTO or the anonymized dispute export.
_FORBIDDEN_NORMALIZED = {
    "userid",
    "ownerid",
    "publisherid",
    "reporterid",
    "finderid",
    "claimantid",
    "claimerid",
    "actorid",
    "accountid",
    "memberid",
    "applicantid",
    "respondentid",
    "realname",
    "username",
    "nickname",
    "displayname",
    "studentid",
    "phone",
    "mobile",
    "phonenumber",
    "email",
    "mail",
    "idnumber",
    "idcard",
    "idcardnumber",
    "identitymapping",
    "identitymap",
    "openid",
    "unionid",
    "publisher",
    "owner",
    "claimant",
    "reporter",
    "actor",
    "createdby",
    "postedby",
    "authorid",
    "user",
}

# ``role``/``my_role`` are explicitly required by the claim contract and are
# therefore not in the forbidden set.
_ALLOWED_ROLE_KEYS = {"role", "myrole", "viewerrole", "senderrole", "actorrole"}

_IDENTITY_ACTOR_NAMES = ("alice", "bob", "finder", "outsider")


class PrivacyViolation(AssertionError):
    """A response exposed an identity field that the public contract forbids."""


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def iter_forbidden_keys(value: Any, path: str = "$") -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalize_key(str(key))
            if normalized in _FORBIDDEN_NORMALIZED and normalized not in {
                _normalize_key(item) for item in _ALLOWED_ROLE_KEYS
            }:
                # ``user`` is only forbidden when it carries an identity object;
                # a string "user" would be unusual, so flag it anyway.
                yield f"{path}.{key}"
            yield from iter_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_forbidden_keys(child, f"{path}[{index}]")


def assert_no_identity_fields(payload: Any, *, context: str = "response") -> None:
    forbidden = list(iter_forbidden_keys(payload))
    if forbidden:
        raise PrivacyViolation(
            f"{context} exposed forbidden identity field(s): {', '.join(forbidden)}"
        )


def assert_no_actor_identifiers(
    payload: Any, *, context: str = "dispute export", actors: Iterable[str] = _IDENTITY_ACTOR_NAMES
) -> None:
    """For the anonymized export: no demo actor label may survive as a token."""

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    leaked = []
    for actor in actors:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(actor)}(?![A-Za-z0-9_])", serialized, re.I):
            leaked.append(actor)
    if leaked:
        raise PrivacyViolation(
            f"{context} contains demo actor identifier(s): {', '.join(sorted(set(leaked)))}"
        )


# Representative, synthetic hard-block cases.  They are not real people's data.
PII_CASES: tuple[tuple[str, str], ...] = (
    ("phone", "13800138000"),
    ("email", "alice.lost@example.com"),
    ("id_card_18", "11010519491231002X"),
    ("id_card_15", "110105194912310"),
)
