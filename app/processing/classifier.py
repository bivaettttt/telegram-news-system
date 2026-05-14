"""
News classifier — routes items to world / economy / discard.

Returns both a category string AND a confidence score (0.0–1.0).
Confidence < 0.55 triggers moderation review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Filter lists (discard before scoring)
# ---------------------------------------------------------------------------

_SPORT_KW = [
    "premier league", "match", "football", "soccer", "goal", "aston villa",
    "manchester united", "championship", "live:", "формул", "ферстаппен",
    "паралимпиад", "олимпиад", "лыжник", "лыжниц", "футбол", "хоккей",
    "баскетбол", "теннис", "formula 1", "f1 race", "grand prix",
]

_LOCAL_NOISE_KW = [
    "погода", "температур", "снег", "дожд", "москвич", "коммуналь", "жкх",
    "актёр", "актриса", "артист", "шоубизнес", "кино", "сериал", "звезда",
    "дтп", "трамва", "пожар", "внуково", "шереметьево", "домодедово",
]

_LOW_SIGNAL_KW = [
    "data download", "selected interest rates", "historical data correction",
    "weekly report", "statistical annex", "technical standards",
    "consultation paper", "h15:", "h41:", "z1:", "g17:", "g20:", "cp:",
    "press digest", "calendar reminder",
    # CBR технические таблицы — не нужны в ленте
    "pffl", "dirrepoauction", "UniDbQuery", "File/90134",
    # Явно устаревшие или информационные страницы
    "архив данных", "исторические данные",
]

# ---------------------------------------------------------------------------
# Scoring keyword lists
# ---------------------------------------------------------------------------

_WORLD_KW = [
    # Conflicts & military
    ("война", 3), ("удар", 2), ("атака", 2), ("обстрел", 2), ("ракета", 2),
    ("дрон", 2), ("бпла", 2), ("военн", 2), ("фронт", 2), ("взрыв", 2),
    ("теракт", 3), ("вооружён", 2), ("армия", 1),
    # Diplomacy
    ("переговор", 2), ("санкц", 2), ("саммит", 2), ("мид", 2), ("посольств", 1),
    ("дипломат", 2), ("договор", 1), ("соглашени", 1), ("меморандум", 1),
    # Orgs & alliances
    ("нато", 2), ("оон", 2), ("евросоюз", 2), ("ес ", 1), ("нато", 2),
    # Leaders & politics
    ("президент", 1), ("премьер", 1), ("парламент", 1), ("министр", 1),
    ("выборы", 2), ("референдум", 2), ("кризис", 1), ("протест", 1),
    # English keywords
    ("war", 2), ("strike", 2), ("missile", 2), ("drone", 2), ("conflict", 2),
    ("ceasefire", 3), ("trump", 1), ("zelensky", 1), ("putin", 1),
    ("sanctions", 2), ("summit", 2), ("nato", 2), ("coup", 3), ("attack", 2),
    ("geopolit", 2), ("diplomat", 2), ("nuclear", 2),
]

_ECONOMY_KW = [
    # Monetary policy
    ("ставк", 3), ("ключевая ставка", 4), ("цб ", 3), ("центробанк", 3),
    ("банк России", 3), ("фрс", 3), ("fed ", 3), ("ecb", 3), ("boe", 3),
    ("boj", 3), ("interest rate", 3), ("инфляц", 3), ("cpi", 3),
    # Markets
    ("рынк", 2), ("бирж", 2), ("акци", 2), ("облигац", 2), ("доходност", 2),
    ("индекс", 2), ("s&p", 3), ("nasdaq", 3), ("ммвб", 3), ("imoex", 3),
    # Currencies & commodities
    ("нефть", 3), ("газ", 2), ("спг", 3), ("опек", 3), ("баррел", 3),
    ("рубл", 2), ("доллар", 2), ("евро", 2), ("валют", 2), ("курс", 2),
    # Banking & credit
    ("банк", 2), ("кредит", 2), ("ипотек", 3), ("депозит", 2),
    ("вклад", 2), ("ликвидност", 2), ("резерв", 1),
    # Macro
    ("ввп", 3), ("gdp", 3), ("бюджет", 2), ("налог", 2), ("дефицит", 2),
    ("профицит", 2), ("инвестиц", 2), ("торговый", 2), ("экспорт", 2),
    ("импорт", 2), ("пошлин", 2), ("тариф", 2), ("санкции против", 2),
    # Crypto (only market-relevant)
    ("bitcoin", 2), ("крипт", 1), ("ethereum", 1),
    # English
    ("economy", 2), ("inflation", 3), ("gdp", 3), ("bond", 2), ("yield", 2),
    ("stocks", 2), ("equity", 2), ("oil", 3), ("forex", 2), ("bank", 1),
    ("fiscal", 2), ("monetary", 3), ("recession", 3), ("trade war", 3),
]

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    category: str          # "world" | "economy" | "discard"
    confidence: float      # 0.0 – 1.0
    world_score: int
    economy_score: int
    reasons: list[str]

    @property
    def needs_moderation(self) -> bool:
        return self.category != "discard" and self.confidence < 0.55


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(*parts: str | None) -> str:
    return " ".join((p or "") for p in parts).lower().strip()


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


def _score(text: str, weighted_kw: list[tuple[str, int]]) -> int:
    return sum(w for k, w in weighted_kw if k in text)


def _matches_any_re(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_news(
    title: str | None,
    text: str | None,
    source_name: str | None = None,
    source_category_hint: str | None = None,
) -> str:
    """Simple string interface — returns 'world' | 'economy' | 'discard'."""
    return classify_news_detailed(title, text, source_name, source_category_hint).category


def classify_news_detailed(
    title: str | None,
    text: str | None,
    source_name: str | None = None,
    source_category_hint: str | None = None,
) -> ClassificationResult:
    """Full classification with confidence score and reasoning."""
    blob = _norm(title, text, source_name)
    reasons: list[str] = []

    if not blob:
        return ClassificationResult("discard", 1.0, 0, 0, ["empty content"])

    # — Hard filters —
    if _contains_any(blob, _SPORT_KW):
        return ClassificationResult("discard", 1.0, 0, 0, ["sport content"])
    if _contains_any(blob, _LOW_SIGNAL_KW):
        return ClassificationResult("discard", 1.0, 0, 0, ["low-signal/technical content"])
    if _contains_any(blob, _LOCAL_NOISE_KW) and not any(k in blob for k, _ in _ECONOMY_KW[:10]):
        return ClassificationResult("discard", 0.9, 0, 0, ["local noise"])

    # — Score —
    w_score = _score(blob, _WORLD_KW)
    e_score = _score(blob, _ECONOMY_KW)

    # — Source hint bias —
    if source_category_hint == "economy":
        e_score = int(e_score * 1.3) + 2
        reasons.append("source hint: economy")
    elif source_category_hint == "world":
        w_score = int(w_score * 1.3) + 2
        reasons.append("source hint: world")

    total = w_score + e_score

    if total == 0:
        return ClassificationResult("discard", 0.7, 0, 0, ["no relevant keywords"])

    # — Category decision —
    if e_score >= 6 and w_score <= 2:
        category = "economy"
        confidence = min(0.95, 0.65 + (e_score - w_score) * 0.03)
        reasons.append(f"strong economy score: {e_score}")
    elif w_score >= 6 and e_score <= 2:
        category = "world"
        confidence = min(0.95, 0.65 + (w_score - e_score) * 0.03)
        reasons.append(f"strong world score: {w_score}")
    elif e_score > w_score:
        category = "economy"
        delta = e_score - w_score
        confidence = 0.50 + min(0.35, delta * 0.04)
        reasons.append(f"economy leads: {e_score} vs {w_score}")
    elif w_score > e_score:
        category = "world"
        delta = w_score - e_score
        confidence = 0.50 + min(0.35, delta * 0.04)
        reasons.append(f"world leads: {w_score} vs {e_score}")
    else:
        # Tie — apply source hint or default world
        if source_category_hint in ("economy",):
            category = "economy"
        else:
            category = "world"
        confidence = 0.45
        reasons.append(f"tie: w={w_score} e={e_score}, defaulting to {category}")

    # — Special cross-channel logic —
    # "Sanctions on oil" → economy even if geopolitical keywords present
    if "санкции" in blob and any(x in blob for x in ["нефть", "газ", "экспорт", "нефтяной"]):
        if category == "world":
            category = "economy"
            confidence = max(confidence, 0.70)
            reasons.append("sanctions+energy → economy override")

    return ClassificationResult(category, round(confidence, 3), w_score, e_score, reasons)
