"""
Quality check task — scores and filters news items after rewrite.

Writes quality_score and marks is_relevant=False for trash items.
"""
from __future__ import annotations

import re

from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.news_item import NewsItem
from app.models.source import Source  # важно: регистрирует таблицу sources для FK

logger = setup_logger("quality_check")

BATCH_LIMIT = 300
MIN_QUALITY_SCORE = 4

_SPORT_RE = [
    r"\bспорт\b", r"\bматч\b", r"\bгол\b", r"\bчемпионат\b", r"\bлига\b",
    r"\bфутбол", r"\bхоккей", r"\bтеннис", r"\bformula 1\b", r"\bформул[аы]\b",
    r"\bpremier league\b", r"\bmanchester\b", r"\bchampions league\b",
]
_LOW_VALUE_RE = [
    r"\bvideo\b", r"\bvideos\b", r"\bphoto gallery\b", r"\bpodcast\b",
    r"\bпогод", r"\bтемператур", r"\bшоубизнес", r"\bактёр", r"\bактрис",
    r"\bдтп\b", r"\bтрамва", r"\bвнуково\b", r"\bшереметьево\b",
]
_TECH_RE = [
    r"^h15:", r"^h41:", r"^z1:", r"^g17:", r"^g20:", r"^cp:",
    r"\bselected interest rates\b", r"\bdata download\b",
    r"\bstatistical annex\b", r"\bpolicy rates\b",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def compute_quality_score(item: NewsItem) -> int:
    title = (item.title_ru or item.title_original or "").lower().strip()
    summary = (item.summary_ru or item.text_original or "").lower().strip()
    blob = f"{title} {summary}"

    if not blob.strip():
        return 0

    score = 0

    # Title quality
    if len(title) >= 30:
        score += 4
    elif len(title) >= 18:
        score += 3
    elif len(title) >= 12:
        score += 2

    # Summary quality
    if len(summary) >= 500:
        score += 5
    elif len(summary) >= 250:
        score += 4
    elif len(summary) >= 120:
        score += 3
    elif len(summary) >= 60:
        score += 2
    elif len(summary) >= 30:
        score += 1

    # Topic signal bonus
    world_kw = [
        "война", "удар", "атака", "санкц", "переговор", "президент", "министр",
        "war", "strike", "missile", "ceasefire", "summit", "sanctions",
    ]
    econ_kw = [
        "эконом", "инфляц", "ставк", "банк", "рынк", "нефть", "газ", "кредит",
        "inflation", "rate", "bank", "oil", "gdp", "fiscal", "monetary",
    ]
    if any(k in blob for k in world_kw):
        score += 2
    if any(k in blob for k in econ_kw):
        score += 2

    # Media bonus
    if item.image_url:
        score += 1
    if item.video_url:
        score += 2

    # LLM enrichment bonus
    if item.why_important_ru and len(item.why_important_ru) > 20:
        score += 1
    if item.market_impact_ru and len(item.market_impact_ru) > 20:
        score += 1

    # Penalties
    if _matches_any(blob, _SPORT_RE):
        score -= 20
    if _matches_any(blob, _LOW_VALUE_RE):
        score -= 10
    if _matches_any(title, _TECH_RE):
        score -= 15
    if title in ("без заголовка", "untitled", ""):
        score -= 15

    return max(score, 0)


def main() -> None:
    db = SessionLocal()
    try:
        items = (
            db.query(NewsItem)
            .filter(
                NewsItem.rewrite_status == "done",
                NewsItem.quality_score == 0,
                NewsItem.category.is_not(None),
                NewsItem.category != "discard",
            )
            .limit(BATCH_LIMIT)
            .all()
        )

        if not items:
            logger.debug("No items to quality-check")
            return

        filtered = 0
        for item in items:
            score = compute_quality_score(item)
            item.quality_score = score

            if score < MIN_QUALITY_SCORE:
                item.is_relevant = False
                item.status = "filtered"
                filtered += 1

        db.commit()
        logger.info(
            "Quality check: %d items | %d filtered (score < %d)",
            len(items),
            filtered,
            MIN_QUALITY_SCORE,
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()