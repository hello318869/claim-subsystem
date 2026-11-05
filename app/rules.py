"""Pure policy functions: contact-info filtering and explainable match scoring.

Both are deliberately side-effect free so they can be unit tested without a database and
their versions can be frozen in evaluation reports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

RULE_VERSION = "rules-v1.0"
MATCH_THRESHOLD = 40
CANDIDATE_LIMIT = 3

WEIGHT_CATEGORY = 35
WEIGHT_TEXT = 30
WEIGHT_LOCATION = 20
WEIGHT_TIME = 15

_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_ID_CARD = re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])")
_ID_CARD_15 = re.compile(r"(?<!\d)\d{15}(?!\d)")


@dataclass(frozen=True)
class ContactHit:
    kind: str
    preview: str


def scan_contact_info(text: str) -> list[ContactHit]:
    """Return every contact-like fragment in ``text``.

    Numeric boundaries are required so common item numbers such as ``ASSET-2026-0042`` pass.
    Longer digit runs that happen to look like an ID card are still rejected: the accepted
    trade-off is documented, and such numbers belong in the private evidence field.
    """
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


def _tokens(text: str) -> set[str]:
    lowered = (text or "").lower()
    words = {token for token in re.split(r"[^0-9a-z\u4e00-\u9fff]+", lowered) if len(token) >= 3}
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", lowered)
    bigrams = {cjk[i : i + 2] for i in range(len(cjk) - 1)}
    return words | bigrams


def _text_score(lost_title: str, lost_description: str, found_title: str, found_description: str) -> tuple[int, int]:
    lost_tokens = _tokens(f"{lost_title} {lost_description}")
    if not lost_tokens:
        return 0, 0
    found_tokens = _tokens(f"{found_title} {found_description}")
    overlap = lost_tokens & found_tokens
    ratio = len(overlap) / len(lost_tokens)
    return round(WEIGHT_TEXT * min(ratio, 1.0)), len(overlap)


def _location_score(lost_location: str, found_location: str) -> int:
    left = (lost_location or "").strip()
    right = (found_location or "").strip()
    if not left or not right:
        return 0
    if left == right or left in right or right in left:
        return WEIGHT_LOCATION
    if left[:2] == right[:2]:
        return 12
    return 0


def _time_score(lost_at: datetime, found_at: datetime) -> int:
    days = abs((found_at - lost_at).total_seconds()) / 86400
    if days <= 3:
        return WEIGHT_TIME
    if days <= 7:
        return 10
    if days <= 30:
        return 5
    return 0


@dataclass(frozen=True)
class Candidate:
    item_id: str
    score: int
    reasons: tuple[str, ...]


def score_pair(
    *,
    lost_title: str,
    lost_description: str,
    lost_category: str,
    lost_location: str,
    lost_at: datetime,
    found_title: str,
    found_description: str,
    found_category: str,
    found_location: str,
    found_at: datetime,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if lost_category and lost_category == found_category:
        score += WEIGHT_CATEGORY
        reasons.append(f"类别一致：{lost_category}")

    text_score, overlap_count = _text_score(lost_title, lost_description, found_title, found_description)
    if text_score:
        score += text_score
        reasons.append(f"描述关键词重合 {overlap_count} 项")

    location_score = _location_score(lost_location, found_location)
    if location_score:
        score += location_score
        reasons.append("地点一致" if location_score == WEIGHT_LOCATION else "地点相近")

    time_score = _time_score(lost_at, found_at)
    if time_score:
        score += time_score
        reasons.append("时间接近")

    return score, reasons


def rank_candidates(
    lost: object,
    founds: list[object],
    *,
    threshold: int = MATCH_THRESHOLD,
    limit: int = CANDIDATE_LIMIT,
) -> list[Candidate]:
    scored: list[Candidate] = []
    for found in founds:
        score, reasons = score_pair(
            lost_title=lost.title,
            lost_description=lost.description,
            lost_category=lost.category,
            lost_location=lost.location,
            lost_at=lost.occurred_at,
            found_title=found.title,
            found_description=found.description,
            found_category=found.category,
            found_location=found.location,
            found_at=found.occurred_at,
        )
        if score >= threshold:
            scored.append(Candidate(item_id=found.item_id, score=score, reasons=tuple(reasons)))
    scored.sort(key=lambda candidate: (-candidate.score, candidate.item_id))
    return scored[:limit]
