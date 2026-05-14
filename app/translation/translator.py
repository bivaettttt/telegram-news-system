from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator


MAX_TRANSLATE_CHARS = 4500


def _clean_text_for_translate(text: str | None) -> str:
    if not text:
        return ""

    value = str(text)
    value = html.unescape(value)

    if "<" in value and ">" in value:
        try:
            value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
        except Exception:
            pass

    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"www\.\S+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    if len(value) > MAX_TRANSLATE_CHARS:
        value = value[:MAX_TRANSLATE_CHARS].rsplit(" ", 1)[0].strip()

    return value


def translate_text_to_ru(text: str | None) -> str:
    cleaned = _clean_text_for_translate(text)
    if not cleaned:
        return ""

    try:
        translated = GoogleTranslator(source="auto", target="ru").translate(cleaned)
        return translated or ""
    except Exception as exc:
        print(f"[TRANSLATE ERROR] {str(exc)[:300]}")
        return ""


def normalize_russian_fields(
    original_language: str | None,
    title_original: str | None,
    text_original: str | None,
) -> tuple[str, str]:
    title_original = title_original or ""
    text_original = text_original or ""

    clean_title = _clean_text_for_translate(title_original)
    clean_text = _clean_text_for_translate(text_original)

    if original_language == "ru":
        return clean_title, clean_text

    title_ru = translate_text_to_ru(clean_title)
    summary_ru = translate_text_to_ru(clean_text) if clean_text else ""

    return title_ru, summary_ru