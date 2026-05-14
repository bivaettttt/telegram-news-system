"""
Telegram post formatter — два стиля для Brief | World и Brief | Economy.

Brief | World  — резкий, захватывающий, современный. Сначала удар, потом факты.
Brief | Economy — деловой, конкретный, цифры на первом месте.

ИЗМЕНЕНИЯ v3:
  - Убран блок «Почему важно» — заменён на насыщенный summary
  - Добавлены Telegram-ручки источников (@handle)
  - Добавлены правовые сноски (иноагенты, нежелательные, запрещённые орг.)
  - Единый стиль кнопки «Открыть источник» везде
  - Единообразный footer: «Сообщает @handle | #тег»
  - Для economy: «По данным @handle | #тег»
"""
from __future__ import annotations

import html
import re

from app.processing.legal_compliance import check_legal_compliance

CAPTION_SAFE_TOTAL_LIMIT = 1000
TITLE_LIMIT = 95
SUMMARY_LIMIT = 500
IMPACT_LIMIT = 150
QUOTE_LIMIT = 100

# ---------------------------------------------------------------------------
# Канальные ручки (подпись в конце поста)
# ---------------------------------------------------------------------------
_CHANNEL_TG_MAP: dict[str, str] = {
    "world":   "@brief_global",
    "economy": "@brief_economy",
}

# Источники → Telegram handles (для отображения рядом с именем источника)
_SOURCE_TG_MAP: dict[str, str] = {
    "тасс": "@tass_agency",
    "тасс — экономика": "@tass_agency",
    "тасс — мир": "@tass_agency",
    "риа новости": "@rian_ru",
    "риа новости — экономика": "@rian_ru",
    "риа новости — мир": "@rian_ru",
    "коммерсантъ": "@kommersant",
    "коммерсантъ — экономика": "@kommersant",
    "коммерсантъ — главные новости": "@kommersant",
    "ведомости": "@vedomosti",
    "рбк": "@rbc_news",
    "рбк — экономика": "@rbc_news",
    "forbes russia": "@forbesrussia",
    "форбс россия": "@forbesrussia",
    "прайм": "@prime1",
    "frank media": "@frank_media",
    "российская газета": "@rgrunews",
    "российская газета — экономика": "@rgrunews",
    "банк России — новое на сайте": "@cbr_official",
    "банк России — пресс-релизы": "@cbr_official",
    "минфин России": "@minfin_russia_official",
    "минфин": "@minfin_russia_official",
    "московская биржа": "@moex_official",
    "oilprice.com": "@oilprice_oil",
    "финмаркет": "@finmarket_ru",
    "интерфакс": "@interfax_russia",
}


def _get_tg_handle(source_name: str) -> str | None:
    key = source_name.strip().lower()
    if key in _SOURCE_TG_MAP:
        return _SOURCE_TG_MAP[key]
    for k, v in _SOURCE_TG_MAP.items():
        if k in key or key in k:
            return v
    return None


def _get_channel_handle(channel_code: str) -> str:
    return _CHANNEL_TG_MAP.get(channel_code.lower(), "@brief_global")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(v: str | None) -> str:
    return (v or "").strip()


def _e(v: str | None) -> str:
    return html.escape(_clean(v), quote=False)


def _norm(v: str | None) -> str:
    return re.sub(r"\s+", " ", _clean(v)).strip()


def _strip_html(v: str | None) -> str:
    text = _norm(v)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _shorten_soft(text: str, limit: int) -> str:
    text = _norm(text)
    if not text:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].strip()
    if not cut:
        cut = text[:limit].strip()
    return cut.rstrip(" ,.;:-") + "…"


def _split_sentences(text: str | None) -> list[str]:
    raw = _strip_html(text)
    if not raw:
        return []
    parts = re.split(r"(?<=[.!?])\s+", raw)
    return [p.strip() for p in parts if p.strip()]


def _complete_summary(
    text: str | None,
    max_sentences: int = 4,
    hard_limit: int = SUMMARY_LIMIT,
) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return ""
    chosen: list[str] = []
    current_len = 0
    for s in sentences:
        add_len = (1 if current_len else 0) + len(s)
        if current_len + add_len > hard_limit:
            break
        chosen.append(s)
        current_len += add_len
        if len(chosen) >= max_sentences:
            break
    if chosen:
        return " ".join(chosen).strip()
    return _shorten_soft(_strip_html(text), hard_limit)


def _plain_len(parts: list[str]) -> int:
    joined = "\n\n".join(parts)
    return len(re.sub(r"<[^>]+>", "", joined))


def _pick_emoji(blob: str, category: str) -> str:
    b = blob.lower()
    if category == "economy":
        if any(x in b for x in ["нефть", "газ", "опек", "баррел", "энергет", "спг"]):
            return "🛢"
        if any(x in b for x in ["ставк", "цб", "fed", "ecb", "ключевая", "центробанк"]):
            return "🏦"
        if any(x in b for x in ["инфляц", "cpi", "ppi"]):
            return "📈"
        if any(x in b for x in ["рубл", "доллар", "евро", "курс", "валют"]):
            return "💱"
        if any(x in b for x in ["биткоин", "bitcoin", "крипт", "btc"]):
            return "₿"
        if any(x in b for x in ["бюджет", "налог", "минфин", "дефицит"]):
            return "📋"
        if any(x in b for x in ["акци", "бирж", "индекс", "ммвб", "nasdaq", "s&p"]):
            return "📊"
        if any(x in b for x in ["банк", "кредит", "ипотек", "вклад"]):
            return "🏦"
        if any(x in b for x in ["санкц", "пошлин", "тариф"]):
            return "🚧"
        return "💼"
    # world
    if any(x in b for x in ["война", "удар", "атака", "ракета", "дрон", "обстрел", "фронт", "бпла"]):
        return "💥"
    if any(x in b for x in ["взрыв", "теракт", "стрельба", "жертв", "погиб"]):
        return "🚨"
    if any(x in b for x in ["переговор", "саммит", "встреча", "визит", "договор"]):
        return "🤝"
    if any(x in b for x in ["санкц", "запрет"]):
        return "🚫"
    if any(x in b for x in ["выбор", "голосован", "парламент", "референдум"]):
        return "🗳️"
    if any(x in b for x in ["космос", "ракет", "спутник", "орбит"]):
        return "🚀"
    return "🌍"


def _pick_tag(blob: str, category: str) -> str:
    b = blob.lower()
    if category == "economy":
        if any(x in b for x in ["нефть", "газ", "опек", "баррел", "спг"]):
            return "#энергорынки"
        if any(x in b for x in ["ставк", "цб", "fed", "ecb", "инфляц", "монет"]):
            return "#монетарка"
        if any(x in b for x in ["рубл", "доллар", "евро", "курс", "валют"]):
            return "#валюты"
        if any(x in b for x in ["акци", "бирж", "индекс", "ipo", "ммвб"]):
            return "#рынки"
        if any(x in b for x in ["биткоин", "bitcoin", "крипт", "btc"]):
            return "#крипто"
        if any(x in b for x in ["бюджет", "налог", "минфин"]):
            return "#бюджет"
        if any(x in b for x in ["банк", "кредит", "ипотек", "вклад"]):
            return "#банки"
        return "#экономика"
    # world
    if any(x in b for x in ["война", "удар", "фронт", "военн", "ракет", "бпла"]):
        return "#война"
    if any(x in b for x in ["иран", "израил", "ближний восток"]):
        return "#БлижнийВосток"
    if any(x in b for x in ["трамп", "сша", "вашингтон", "белый дом"]):
        return "#США"
    if any(x in b for x in ["переговор", "саммит", "дипломат"]):
        return "#дипломатия"
    if any(x in b for x in ["санкц"]):
        return "#санкции"
    if any(x in b for x in ["выбор", "голосован", "парламент"]):
        return "#политика"
    if any(x in b for x in ["китай", "пекин", "кнр"]):
        return "#Китай"
    if any(x in b for x in ["европ", "ес ", "нато", "брюссел"]):
        return "#Европа"
    return "#мир"


# ---------------------------------------------------------------------------
# World: резкий, захватывающий стиль
# ---------------------------------------------------------------------------

def _build_world_post(
    title: str,
    summary: str,
    source_name: str,
    quote_ru: str | None,
    tag: str,
    emoji: str,
    channel_handle: str,
    legal_notes: list[str],
) -> str:
    parts: list[str] = []
    # Заголовок — CAPS, агрессивно и броско
    parts.append(f"<b>{emoji} {_e(title.upper())}</b>")
    if summary:
        parts.append(_e(summary))
    # Цитата
    q = _clean(quote_ru)
    if q and len(q) > 10:
        quote_block = f"<i>«{_e(q)}»</i>"
        if _plain_len(parts + [quote_block]) <= CAPTION_SAFE_TOTAL_LIMIT:
            parts.append(quote_block)
    # Footer: источник | тег  +  ручка канала
    footer = f"{_e(source_name)} | {tag}\n{channel_handle}"
    parts.append(footer)
    for note in legal_notes:
        parts.append(f"<i>{_e(note)}</i>")
    return "\n\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Economy: деловой, Bloomberg-стиль
# ---------------------------------------------------------------------------

def _build_economy_post(
    title: str,
    summary: str,
    source_name: str,
    market_impact_ru: str | None,
    quote_ru: str | None,
    tag: str,
    emoji: str,
    channel_handle: str,
    legal_notes: list[str],
) -> str:
    parts: list[str] = []
    parts.append(f"<b>{emoji} {_e(title)}</b>")
    if summary:
        parts.append(_e(summary))
    # Market impact — только если содержательный
    neutral = ["прямого рыночного", "прямого влияния", "не видно", "нет прямого", "пока неясен", "не ожидается"]
    impact = _clean(market_impact_ru)
    if impact and not any(x in impact.lower() for x in neutral) and len(impact) > 20:
        impact_line = f"📌 <b>Что это значит:</b> {_e(impact)}"
        if _plain_len(parts + [impact_line]) <= CAPTION_SAFE_TOTAL_LIMIT:
            parts.append(impact_line)
    # Цитата
    q = _clean(quote_ru)
    if q and len(q) > 10:
        quote_block = f"<i>«{_e(q)}»</i>"
        if _plain_len(parts + [quote_block]) <= CAPTION_SAFE_TOTAL_LIMIT:
            parts.append(quote_block)
    # Footer: источник | тег  +  ручка канала
    footer = f"{_e(source_name)} | {tag}\n{channel_handle}"
    parts.append(footer)
    for note in legal_notes:
        parts.append(f"<i>{_e(note)}</i>")
    return "\n\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_post_html(
    title_ru: str | None,
    summary_ru: str | None,
    source_name: str,
    category: str | None,
    original_url: str | None = None,
    channel_code: str | None = None,
    why_important_ru: str | None = None,
    market_impact_ru: str | None = None,
    quote_ru: str | None = None,
) -> str:
    effective = (channel_code or category or "world").lower()

    base_title = _norm(title_ru) or (
        "Экономическая новость" if effective == "economy" else "Мировая новость"
    )
    title = _shorten_soft(base_title, TITLE_LIMIT)
    summary = _complete_summary(summary_ru, max_sentences=4, hard_limit=SUMMARY_LIMIT)

    blob = f"{title} {summary}".lower()
    emoji = _pick_emoji(blob, effective)
    tag = _pick_tag(blob, effective)
    channel_handle = _get_channel_handle(effective)

    # Правовая проверка
    legal = check_legal_compliance(title, summary)
    legal_notes = legal.get_footnotes()

    if effective == "economy":
        result = _build_economy_post(
            title=title, summary=summary, source_name=source_name,
            market_impact_ru=market_impact_ru, quote_ru=quote_ru,
            tag=tag, emoji=emoji, channel_handle=channel_handle, legal_notes=legal_notes,
        )
    else:
        result = _build_world_post(
            title=title, summary=summary, source_name=source_name,
            quote_ru=quote_ru, tag=tag, emoji=emoji,
            channel_handle=channel_handle, legal_notes=legal_notes,
        )

    # Финальная защита
    plain = len(re.sub(r"<[^>]+>", "", result))
    if plain > CAPTION_SAFE_TOTAL_LIMIT:
        parts = [f"<b>{emoji} {_e(title)}</b>"]
        short = _complete_summary(summary, max_sentences=2, hard_limit=350)
        if short:
            parts.append(_e(short))
        parts.append(f"{_e(source_name)} | {tag}\n{channel_handle}")
        for note in legal_notes:
            parts.append(f"<i>{_e(note)}</i>")
        result = "\n\n".join(parts).strip()

    return result
