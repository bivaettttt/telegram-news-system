from __future__ import annotations

import re

SPORT_PATTERNS = [
    r"\bспорт\b", r"\bматч\b", r"\bгол\b", r"\bчемпионат\b", r"\bлига\b", r"\bкубок\b",
    r"\bпремьер[- ]лига\b", r"\bпаралимпиад", r"\bолимпиад", r"\bлыжник\b", r"\bлыжниц\b",
    r"\bфутбол", r"\bхоккей", r"\bтеннис", r"\bбаскетбол", r"\bmanchester united\b",
    r"\baston villa\b", r"\bpremier league\b", r"\blive\b", r"\bscore\b", r"\bmatch\b",
    r"\bfootball\b", r"\bsoccer\b", r"\bформул[аы][- ]?1\b", r"\bферстаппен\b",
]

LOW_VALUE_PATTERNS = [
    r"\bvideo\b", r"\bvideos\b", r"\bphoto\b", r"\bphotos\b", r"\bgallery\b", r"\bpodcast\b",
    r"\bтемпературн", r"\bпогод", r"\bшоубизнес", r"\bзнаменит", r"\bакт[её]р", r"\bактрис",
    r"\bдтп\b", r"\bпожар\b", r"\bтрамва", r"\bаэропорт\b", r"\bвнуково\b", r"\bшереметьево\b",
]

TECHNICAL_TITLE_PATTERNS = [
    r"^h15:", r"^h41:", r"^z1:", r"^g17:", r"^g20:", r"^cp:",
    r"\bselected interest rates\b", r"\bdata download\b", r"\bpolicy rates\b",
    r"\bhistorical data correction\b", r"\bstatistical annex\b",
]

BAD_URL_PATTERNS = [
    r"/sport/", r"/sports/", r"/video/", r"/videos/", r"/photoslider/",
    # CBR технические страницы
    r"/pffl", r"/dirrepo", r"/UniDbQuery", r"/File/90134",
    r"/hd_base/", r"/statistics/pffl",
]


def _text(value: str | None) -> str:
    return (value or "").strip()


def _lower(value: str | None) -> str:
    return _text(value).lower()


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def compute_quality_score(title_ru: str | None, summary_ru: str | None, category: str | None) -> int:
    title = _lower(title_ru)
    summary = _lower(summary_ru)
    blob = f"{title} {summary}".strip()
    if not blob:
        return 0

    score = 0
    if len(title) >= 18:
        score += 3
    elif len(title) >= 12:
        score += 2

    if len(summary) >= 220:
        score += 4
    elif len(summary) >= 120:
        score += 3
    elif len(summary) >= 60:
        score += 2
    elif len(summary) >= 24:
        score += 1

    if any(x in blob for x in ["война", "удар", "атака", "санкц", "переговор", "президент", "министр"]):
        score += 2
    if any(x in blob for x in ["эконом", "финанс", "ставк", "инфляц", "банк", "рын", "нефть", "газ", "кредит", "ипотек"]):
        score += 2

    if _matches_any(blob, SPORT_PATTERNS):
        score -= 20
    if _matches_any(blob, LOW_VALUE_PATTERNS):
        score -= 10
    if _matches_any(title, TECHNICAL_TITLE_PATTERNS):
        score -= 15
    if title == "без заголовка":
        score -= 20

    return max(score, 0)


def is_news_relevant(title_ru: str | None, summary_ru: str | None, category: str | None, is_duplicate: bool) -> bool:
    if is_duplicate:
        return False
    title = _lower(title_ru)
    summary = _lower(summary_ru)
    blob = f"{title} {summary}".strip()
    if not title or title == "без заголовка" or len(title) < 10:
        return False
    if _matches_any(blob, SPORT_PATTERNS):
        return False
    if _matches_any(title, TECHNICAL_TITLE_PATTERNS):
        return False
    score = compute_quality_score(title_ru, summary_ru, category)
    return score >= 3


def is_high_quality_news(item) -> bool:
    title = _text(getattr(item, "title_ru", None) or getattr(item, "title_original", None))
    summary = _text(getattr(item, "summary_ru", None) or getattr(item, "text_original", None))
    url = _lower(getattr(item, "original_url", None))
    if not title or title.lower() == "без заголовка" or len(title) < 10:
        return False
    blob = f"{title.lower()} {summary.lower()}".strip()
    if _matches_any(blob, SPORT_PATTERNS):
        return False
    if _matches_any(title.lower(), TECHNICAL_TITLE_PATTERNS):
        return False
    if _matches_any(url, BAD_URL_PATTERNS):
        return False
    score = compute_quality_score(title, summary, getattr(item, "category", None))
    return score >= 3
