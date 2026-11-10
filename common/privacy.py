"""Contact-information filtering for chat messages.

The claim subsystem does not own real identity checks, so the private conversation must not
become a way to publish a phone number, e-mail address or ID number.  This scan is a safety
net, not an identity verification: it only blocks obviously contact-like fragments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_ID_CARD = re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])")
_ID_CARD_15 = re.compile(r"(?<!\d)\d{15}(?!\d)")


@dataclass(frozen=True)
class ContactHit:
    kind: str
    preview: str


def scan_contact_info(text: str) -> list[ContactHit]:
    """Return every contact-like fragment in ``text`` (numeric boundaries keep item numbers)."""
    hits: list[ContactHit] = []
    for kind, pattern in (
        ("mobile", _MOBILE),
        ("email", _EMAIL),
        ("id_card", _ID_CARD),
        ("id_card", _ID_CARD_15),
    ):
        for match in pattern.finditer(text or ""):
            hits.append(ContactHit(kind=kind, preview=match.group(0)[:4] + "***"))
    return hits


def blocks_contact_info(text: str) -> bool:
    return bool(scan_contact_info(text))
