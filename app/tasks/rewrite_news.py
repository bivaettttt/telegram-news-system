"""
Rewrite task — LLM rewrite для классифицированных новостей.

КЛЮЧЕВЫЕ РЕШЕНИЯ:
  - BATCH_LIMIT = 8: Groq free tier llama-3.3-70b = 6 000 TPM.
    ~600 токенов/запрос → 10 запросов до лимита. Берём 8 с запасом.
  - При RateLimitError (429): НЕМЕДЛЕННО останавливаем батч.
    Оставшиеся items → rewrite_status='retry'. Scheduler вернёт через 30 мин.
    НЕ ждём 256 секунд inline — pipeline не должен зависать.
  - При временных ошибках (timeout, 5xx): status='new', rewrite_status='retry'.
  - При постоянных ошибках (валидация, 4xx): status='filtered', rewrite_status='error'.
  - Если LLM отключён: fallback на оригинальный текст.
  - Промежуточный commit каждые 5 items.

  СОВЕТ: Если 429 продолжаются → в .env:
    OPENAI_MODEL=llama-3.1-8b-instant  (30 000 TPM вместо 6 000)
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.llm.client import RateLimitError
from app.llm.rewrite import rewrite_news_to_ru
from app.models.news_item import NewsItem
from app.models.source import Source  # noqa: F401 — нужен для FK

logger = setup_logger("rewrite_news")

BATCH_LIMIT = 8           # Groq free: ~10 запросов до TPM лимита, берём 8
INTER_REQUEST_DELAY = 5.0  # секунд между запросами → ~12 RPM (лимит 14)
COMMIT_EVERY = 5
# Только свежие новости — не публикуем материалы старше 36 часов
FRESHNESS_WINDOW_HOURS = 36


def _fallback_rewrite(item: NewsItem) -> None:
    """Заполняем поля без LLM — публикуем оригинальный текст."""
    item.title_ru = item.title_original or ""
    item.summary_ru = (item.text_original or "")[:800]
    item.why_important_ru = None
    item.market_impact_ru = None
    item.quote_ru = None
    item.rewrite_model = "fallback_no_llm"
    item.rewrite_status = "done"
    item.status = "ready"


def _mark_retry(item: NewsItem) -> None:
    """Помечаем item для повторной попытки — scheduler вернёт через 30 мин."""
    item.rewrite_status = "retry"
    item.status = "new"


def main() -> None:
    db = SessionLocal()
    try:
        # Только свежие новости — старые (> 36ч) отмечаем как filtered чтобы не публиковать устаревшие данные
        freshness_cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=FRESHNESS_WINDOW_HOURS)

        # Сначала помечаем устаревшие как filtered
        stale = (
            db.query(NewsItem)
            .filter(
                NewsItem.rewrite_status.in_(["pending", "retry"]),
                NewsItem.category.is_not(None),
                NewsItem.category != "discard",
                NewsItem.status.notin_(["filtered", "published", "post_created"]),
                NewsItem.fetched_at < freshness_cutoff,
            )
            .all()
        )
        if stale:
            for item in stale:
                item.status = "filtered"
                item.rewrite_status = "error"
            db.commit()
            logger.info("Freshness filter: marked %d stale items (>%dh) as filtered", len(stale), FRESHNESS_WINDOW_HOURS)

        items = (
            db.query(NewsItem)
            .filter(
                NewsItem.rewrite_status.in_(["pending", "retry"]),
                NewsItem.category.is_not(None),
                NewsItem.category != "discard",
                NewsItem.status.notin_(["filtered", "published"]),
                NewsItem.fetched_at >= freshness_cutoff,  # только свежие
            )
            .order_by(NewsItem.importance_score.desc(), NewsItem.fetched_at.desc())
            .limit(BATCH_LIMIT)
            .all()
        )

        if not items:
            logger.debug("No items to rewrite")
            return

        # LLM отключён → fallback на оригинальный текст
        llm_enabled = bool(settings.llm_rewrite_enabled and settings.openai_api_key)
        if not llm_enabled:
            logger.warning(
                "LLM disabled — fallback to original text for %d items", len(items)
            )
            for item in items:
                _fallback_rewrite(item)
            db.commit()
            logger.info("Fallback rewrite done for %d items", len(items))
            return

        logger.info(
            "Rewriting %d items via %s...", len(items), settings.openai_model
        )
        done = 0
        retried = 0
        filtered = 0

        for idx, item in enumerate(items, start=1):
            try:
                (
                    title_ru,
                    summary_ru,
                    why_important_ru,
                    market_impact_ru,
                    quote_ru,
                    model_used,
                ) = rewrite_news_to_ru(
                    category=item.category,
                    original_language=item.original_language,
                    title_original=item.title_original,
                    text_original=item.text_original,
                    url=item.original_url,
                )

                item.title_ru = title_ru
                item.summary_ru = summary_ru
                item.why_important_ru = why_important_ru
                item.market_impact_ru = market_impact_ru
                item.quote_ru = quote_ru
                item.rewrite_model = model_used
                item.rewrite_status = "done"
                item.status = "ready"
                done += 1

            except RateLimitError as exc:
                # 429 — немедленно останавливаем батч, не ждём здесь
                logger.warning(
                    "Rate limit at item %d/%d (retry_after=%ds) — "
                    "stopping batch, %d items → retry",
                    idx, len(items), exc.retry_after,
                    len(items) - idx + 1,
                )
                _mark_retry(item)
                retried += 1
                for remaining in items[idx:]:
                    _mark_retry(remaining)
                    retried += 1
                db.commit()
                logger.info(
                    "Rewrite stopped: %d ok | %d retry | %d filtered",
                    done, retried, filtered,
                )
                return

            except Exception as exc:
                reason = str(exc).strip()[:120] or "rewrite_error"
                is_transient = any(
                    k in reason.lower()
                    for k in ("timeout", "connect", "503", "502")
                )
                if is_transient:
                    logger.warning("Transient error item %d: %s → retry", item.id, reason)
                    _mark_retry(item)
                    retried += 1
                else:
                    logger.error("Permanent error item %d: %s → filtered", item.id, reason)
                    item.rewrite_status = "error"
                    item.status = "filtered"
                    filtered += 1

            # Пауза между запросами (не после последнего)
            if idx < len(items):
                time.sleep(INTER_REQUEST_DELAY)

            # Промежуточный commit
            if idx % COMMIT_EVERY == 0:
                db.commit()

        db.commit()
        logger.info(
            "Rewrite done: %d ok | %d retry | %d filtered",
            done, retried, filtered,
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()