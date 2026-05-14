"""
Moderation router — centralized logic for deciding whether a news item
needs human review or can be auto-published.

PHILOSOPHY:
  - Normal, clearly relevant news → auto-publish
  - Moderation is the EXCEPTION, not the default
  - Only route to moderation when there's genuine uncertainty or risk
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ModerationDecision(str, Enum):
    AUTO_PUBLISH = "auto_publish"
    SEND_TO_MODERATION = "send_to_moderation"
    DISCARD = "discard"


@dataclass
class ModerationResult:
    decision: ModerationDecision
    reason: str
    confidence: float
    flags: list[str] = field(default_factory=list)


_SHOCK_MARKERS = [
    "убийств", "изнасилован", "педофил", "суицид", "самоубийств",
    "расстрелял", "зарезал", "расчленил", "казн", "пытк",
    "murder", "rape", "suicide", "execution", "torture",
]

_RUMOR_MARKERS = [
    "по слухам", "источники говорят", "якобы", "предположительно",
    "по данным анонимных источников", "неподтверждённые данные",
    "по неофициальным данным", "слухи", "rumors", "allegedly",
    "unconfirmed", "sources say", "reportedly",
]

_FAKE_RISK_MARKERS = [
    "фейк", "дезинформация", "манипуляция", "пропаганда",
    "fake", "disinformation", "deepfake", "manipulat",
]

_PERSONAL_ATTACK_MARKERS = [
    "обвиняет", "обвинения против", "арестован за", "осуждён",
    "уголовное дело против", "подозревается в",
]

_CLAIM_WITHOUT_EVIDENCE = [
    "по имеющимся данным", "как сообщают", "как стало известно",
    "как выяснилось", "по имеющейся информации",
]

_WEAK_SOURCE_PATTERNS = [
    r"telegram(me)?\.com", r"t\.me/", r"twitter\.com", r"x\.com",
    r"tiktok\.com", r"reddit\.com", r"4chan", r"pikabu",
]


def _lower(v: str | None) -> str:
    return (v or "").lower().strip()


def _contains_any(text: str, markers: list[str]) -> bool:
    return any(m in text for m in markers)


def _matches_any_re(url: str, patterns: list[str]) -> bool:
    return any(re.search(p, url, re.IGNORECASE) for p in patterns)


def _is_too_short(text: str | None) -> bool:
    return len((text or "").strip()) < 40


def _is_too_short_title(title: str | None) -> bool:
    return len((title or "").strip()) < 10


def decide_moderation(
    title_ru: str | None,
    summary_ru: str | None,
    category: str | None,
    classification_confidence: float,
    trust_score: float,
    quality_score: int,
    original_url: str | None,
    is_duplicate: bool,
    source_type: str | None = None,
) -> ModerationResult:
    """
    Returns a ModerationResult with the routing decision.

    Strategy:
    1. Discard only obviously bad items
    2. Auto-publish clearly good items
    3. Route to moderation only for materially risky combinations
    4. Otherwise auto-publish
    """
    flags: list[str] = []
    blob_title = _lower(title_ru)
    blob_summary = _lower(summary_ru)
    blob = f"{blob_title} {blob_summary}"
    url_lower = _lower(original_url)

    # DISCARD: only hard failures
    if is_duplicate:
        return ModerationResult(
            ModerationDecision.DISCARD,
            "duplicate",
            1.0,
            ["is_duplicate"],
        )

    if category == "discard":
        return ModerationResult(
            ModerationDecision.DISCARD,
            "classified as discard",
            1.0,
            ["category=discard"],
        )

    if quality_score < 2:
        return ModerationResult(
            ModerationDecision.DISCARD,
            f"quality_score too low: {quality_score}",
            1.0,
            ["low_quality"],
        )

    if _is_too_short_title(title_ru) and _is_too_short(summary_ru):
        return ModerationResult(
            ModerationDecision.DISCARD,
            "title and summary too short",
            1.0,
            ["too_short"],
        )

    # FAST AUTO-PUBLISH
    if (
        classification_confidence >= 0.65
        and trust_score >= 0.60
        and quality_score >= 4
        and not _contains_any(blob, _SHOCK_MARKERS)
        and not _contains_any(blob, _RUMOR_MARKERS)
        and not _contains_any(blob, _FAKE_RISK_MARKERS)
        and not _matches_any_re(url_lower, _WEAK_SOURCE_PATTERNS)
        and source_type not in ("social", "blog", "aggregator", "unknown")
    ):
        return ModerationResult(
            ModerationDecision.AUTO_PUBLISH,
            "good confidence + sufficient trust + acceptable quality",
            classification_confidence,
        )

    # Collect soft flags
    low_conf = classification_confidence < 0.35
    low_trust = trust_score < 0.40
    weak_quality = quality_score < 3
    shock = _contains_any(blob, _SHOCK_MARKERS)
    rumor = _contains_any(blob, _RUMOR_MARKERS)
    fake_risk = _contains_any(blob, _FAKE_RISK_MARKERS)
    personal_attack = _contains_any(blob, _PERSONAL_ATTACK_MARKERS)
    weak_domain = _matches_any_re(url_lower, _WEAK_SOURCE_PATTERNS)
    weak_source_type = source_type in ("social", "blog", "aggregator", "unknown")
    claim_wo_evidence = _contains_any(blob, _CLAIM_WITHOUT_EVIDENCE)

    if low_conf:
        flags.append(f"low_routing_confidence:{classification_confidence:.2f}")
    if low_trust:
        flags.append(f"low_trust_score:{trust_score:.2f}")
    if weak_quality:
        flags.append(f"low_quality_for_review:{quality_score}")
    if shock:
        flags.append("shock_content")
    if rumor:
        flags.append("rumors_markers")
    if fake_risk:
        flags.append("fake_risk_markers")
    if personal_attack:
        flags.append("personal_accusations")
    if weak_domain:
        flags.append("weak_source_domain")
    if weak_source_type:
        flags.append(f"weak_source_type:{source_type}")
    if claim_wo_evidence:
        flags.append("claim_without_evidence")

    # MODERATION: only for risky combinations, not any single weak signal
    risky_combo = False

    if shock:
        risky_combo = True

    if rumor and (low_trust or weak_domain or weak_source_type):
        risky_combo = True

    if fake_risk:
        risky_combo = True

    if personal_attack and (rumor or low_trust):
        risky_combo = True

    if weak_domain and low_trust and weak_quality:
        risky_combo = True

    if weak_source_type and low_trust and (rumor or claim_wo_evidence):
        risky_combo = True

    if low_conf and low_trust and weak_quality:
        risky_combo = True

    if risky_combo:
        reason = "; ".join(flags[:3]) if flags else "risky_combination"
        return ModerationResult(
            ModerationDecision.SEND_TO_MODERATION,
            reason,
            classification_confidence,
            flags,
        )

    # DEFAULT: auto-publish
    return ModerationResult(
        ModerationDecision.AUTO_PUBLISH,
        "passed relaxed moderation",
        classification_confidence,
        flags,
    )


def format_moderation_message(
    post_id: int,
    channel_name: str,
    post_text_html: str,
    moderation_result: ModerationResult,
) -> str:
    """Build the message sent to the moderation chat."""
    flag_str = " | ".join(moderation_result.flags[:5]) if moderation_result.flags else "—"
    return (
        f"<b>⚠️ МОДЕРАЦИЯ</b>\n"
        f"<b>Post ID:</b> {post_id} | <b>Канал:</b> {channel_name}\n"
        f"<b>Причина:</b> {moderation_result.reason}\n"
        f"<b>Флаги:</b> {flag_str}\n"
        f"<b>Уверенность:</b> {moderation_result.confidence:.0%}\n\n"
        f"{post_text_html}"
    )