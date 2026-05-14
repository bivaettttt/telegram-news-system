"""
LLM rewrite layer — генерирует насыщенный русский текст для Telegram-постов.

Brief | World  — резкий, захватывающий стиль. Факты + реакция + контекст.
Brief | Economy — деловой, Bloomberg-стиль. Цифры + что это значит + контекст.

«Почему важно» убран — вместо этого summary делается насыщеннее.
"""
from __future__ import annotations

import re

from app.llm.client import LLMClientError, RateLimitError, ResponsesClient
from app.translation.translator import normalize_russian_fields


WORLD_SYSTEM = """Ты — редактор Telegram-канала «Brief | World» — острые мировые новости.

СТИЛЬ КАНАЛА: Резкий, захватывающий. Читатель должен захотеть дочитать до конца и поделиться постом.
Лексика современная, живая. Никакой бюрократии и скучных клише.

ЗАДАЧА: Переписать международную новость в готовый пост.

ТРЕБОВАНИЯ:
- Только факты из исходного текста. НЕ придумывай.
- title_ru: 1 строка, до 85 символов. Резкий, конкретный: «Иран открылся для тайных переговоров с США», не «Новости дипломатии».
  Используй сильные глаголы: рухнул, взлетел, разорвал, пригрозил, перевернул.
- summary_ru: 4 полных предложения, МИНИМУМ 250 символов.
  • Предложение 1 — главный факт (кто, что, когда — чётко и жёстко).
  • Предложение 2 — детали, цифры, конкретика.
  • Предложение 3 — реакция сторон или что говорят эксперты.
  • Предложение 4 — что будет дальше / почему это важно прямо сейчас.
- market_impact_ru: «—» (для геополитики без рыночной составляющей), или 1 предложение о рыночном эффекте.
- quote_ru: дословная цитата из текста до 100 символов, или пустая строка.
- Весь текст на русском. Имена — транслитерируй.
- Без списков, без markdown, без HTML-тегов.

Верни ТОЛЬКО JSON:
{
  "title_ru": "...",
  "summary_ru": "...",
  "market_impact_ru": "...",
  "quote_ru": ""
}""".strip()


ECONOMY_SYSTEM = """Ты — редактор Telegram-канала «Brief | Economy» — экономика и рынки.

СТИЛЬ КАНАЛА: Деловой, как Bloomberg или РБК Pro. Цифры на первом месте. Чёткий анализ.
Читатель — инвестор, предприниматель, аналитик. Ему нужны факты и их смысл.

ЗАДАЧА: Переписать экономическую новость в готовый пост.

ТРЕБОВАНИЯ:
- Только факты из исходного текста. НЕ придумывай цифры.
- title_ru: 1 строка, до 85 символов. Обязательно с цифрой/фактом: «ЦБ сохранил ставку 15,5%», «Нефть упала ниже $70».
- summary_ru: 4 полных предложения, МИНИМУМ 250 символов.
  • Предложение 1 — ключевой факт с цифрами.
  • Предложение 2 — детали: кто принял решение, при каких условиях.
  • Предложение 3 — контекст: как соотносится с предыдущими данными / трендом.
  • Предложение 4 — что это значит для бизнеса, инвесторов или потребителей.
- market_impact_ru: 1 предложение до 120 символов — конкретный рыночный эффект.
  Хорошо: «Решение давит на рубль и осложняет рефинансирование корпоративных долгов.»
  Нейтральный случай: «Прямого влияния на рынки пока не ожидается.»
- quote_ru: дословная цитата из текста до 100 символов, или пустая строка.
- Весь текст на русском. Без списков, без markdown, без HTML-тегов.

Верни ТОЛЬКО JSON:
{
  "title_ru": "...",
  "summary_ru": "...",
  "market_impact_ru": "...",
  "quote_ru": ""
}""".strip()


def _fallback_market_impact(category: str | None, summary: str) -> str:
    text = (summary or "").lower()
    if category != "economy":
        return "—"
    if any(x in text for x in ["ставк", "цб", "фрс", "ecb", "ключевая"]):
        return "Главный канал влияния — ожидания по ставкам, облигациям и курсу рубля."
    if any(x in text for x in ["нефть", "газ", "опек", "баррел"]):
        return "Главный канал влияния — цены на сырьё и инфляционные ожидания."
    if any(x in text for x in ["рубл", "доллар", "евро", "курс валют"]):
        return "Влияние может проявиться через валютный рынок."
    return "Прямого влияния на рынки пока не ожидается."


def _trim(text: str | None, max_chars: int) -> str:
    value = " ".join((text or "").split()).strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars - 1].rstrip() + "…"


def _looks_non_russian(text: str | None) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    cyr = len(re.findall(r"[А-Яа-яЁё]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    return cyr < 20 and latin > cyr


def _is_valid_rewrite(title_ru: str, summary_ru: str) -> bool:
    if not title_ru or not summary_ru:
        return False
    if len(title_ru.strip()) < 12:
        return False
    if len(summary_ru.strip()) < 160:
        return False
    if _looks_non_russian(title_ru) or _looks_non_russian(summary_ru):
        return False
    return True


def rewrite_news_to_ru(
    category: str | None,
    original_language: str | None,
    title_original: str | None,
    text_original: str | None,
    url: str | None = None,
) -> tuple[str, str, str, str, str, str]:
    """
    Returns: (title_ru, summary_ru, why_important_ru, market_impact_ru, quote_ru, model_used)
    why_important_ru возвращается как пустая строка (убрано из постов).
    """
    title_fallback, summary_fallback = normalize_russian_fields(
        original_language=original_language,
        title_original=title_original,
        text_original=text_original,
    )

    client = ResponsesClient()
    if not client.enabled:
        raise ValueError("LLM client disabled")

    system_prompt = ECONOMY_SYSTEM if category == "economy" else WORLD_SYSTEM
    input_text = _trim(text_original or "", 3500)

    user_prompt = (
        f"Категория: {category or 'world'}\n"
        f"Источник: {url or 'неизвестен'}\n\n"
        f"Оригинальный заголовок:\n{title_original or ''}\n\n"
        f"Оригинальный текст:\n{input_text}"
    )

    try:
        result = client.create_json(system_prompt, user_prompt)
    except RateLimitError:
        raise
    except LLMClientError as exc:
        raise ValueError(f"LLM error: {exc}") from exc

    title_ru = _trim(result.get("title_ru") or title_fallback or "", 110)
    summary_ru = _trim(result.get("summary_ru") or summary_fallback or "", 1000)
    why_important_ru = ""  # Убрано из постов, но поле сохраняем пустым
    market_impact_ru = _trim(
        result.get("market_impact_ru") or _fallback_market_impact(category, summary_ru),
        240,
    )
    quote_ru = _trim(result.get("quote_ru") or "", 140)

    if not _is_valid_rewrite(title_ru, summary_ru):
        raise ValueError(
            f"rewrite validation failed: title={len(title_ru)}chars, "
            f"summary={len(summary_ru)}chars"
        )

    return (title_ru, summary_ru, why_important_ru, market_impact_ru, quote_ru, client.model)
