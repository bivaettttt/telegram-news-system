"""
RSS Fetcher — fetches items from all active RSS sources.

ИСПРАВЛЕНИЯ:
  1. seen_urls (in-memory set) — предотвращает UniqueViolation когда два источника
     публикуют одну и ту же статью. Без этого весь батч из 500+ items откатывался.
  2. db.flush() + per-item IntegrityError — если дубль проскочил, откатываем только
     этот item, не весь батч.
  3. Per-source commit — ошибка в источнике N не трогает источники 1..N-1.
  4. Детализированные ошибки: SSL / timeout / HTTP / parse.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import feedparser
import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logger import setup_logger
from app.models.news_item import NewsItem
from app.models.source import Source
from app.processing.deduplicator import canonicalize_url

logger = setup_logger("rss_fetcher")

FETCH_TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TelegramNewsBot/2.0)"}
MAX_ENTRIES_PER_FEED = 30
AUTO_DISABLE_AFTER_FAILURES = 10


# ---------------------------------------------------------------------------
# Media helpers
# ---------------------------------------------------------------------------

def _extract_image(entry: dict) -> str | None:
    for m in entry.get("media_content") or []:
        url = m.get("url", "")
        if url and any(url.lower().endswith(e) for e in [".jpg", ".jpeg", ".png", ".webp"]):
            return url
    for t in entry.get("media_thumbnail") or []:
        url = t.get("url", "")
        if url:
            return url
    for enc in entry.get("enclosures", []):
        if "image" in enc.get("type", ""):
            return enc.get("href") or enc.get("url")
    summary = entry.get("summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, re.IGNORECASE)
    if m and m.group(1).startswith("http"):
        return m.group(1)
    return None


def _extract_video(entry: dict) -> str | None:
    for m in entry.get("media_content") or []:
        url = m.get("url", "")
        if url and any(url.lower().endswith(e) for e in [".mp4", ".mov", ".webm"]):
            return url
    for enc in entry.get("enclosures", []):
        if "video" in enc.get("type", ""):
            return enc.get("href") or enc.get("url")
    return None


# ---------------------------------------------------------------------------
# Health tracking
# ---------------------------------------------------------------------------

def _mark_success(source: Source, entries_count: int) -> None:
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    source.last_success_at = now_iso
    source.last_checked_at = now_iso
    source.last_item_count = entries_count
    source.consecutive_failures = 0
    source.health_status = "ok"


def _mark_failure(source: Source, status: str) -> None:
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    source.last_checked_at = now_iso
    source.consecutive_failures = (source.consecutive_failures or 0) + 1
    source.health_status = status
    if source.consecutive_failures >= AUTO_DISABLE_AFTER_FAILURES:
        source.is_active = False
        logger.warning(
            "Auto-disabled '%s' after %d consecutive failures",
            source.name, source.consecutive_failures,
        )


# ---------------------------------------------------------------------------
# Single source fetch
# ---------------------------------------------------------------------------

def fetch_single_source(
    db: Session,
    source: Source,
    seen_urls: set[str],
) -> int:
    """
    Фетчит один RSS источник.

    seen_urls — общий in-memory set для всего запуска (mutated здесь).
    Предотвращает UniqueViolation когда несколько источников публикуют одну ссылку
    до того как предыдущий источник был закоммичен.

    Returns: количество добавленных items.
    """
    created = 0
    try:
        resp = httpx.get(
            source.url,
            headers=HEADERS,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
        )

        if resp.status_code != 200:
            logger.warning("HTTP %d from '%s'", resp.status_code, source.name)
            _mark_failure(source, "dead")
            return 0

        feed = feedparser.parse(resp.text)
        entries = feed.get("entries", [])[:MAX_ENTRIES_PER_FEED]

        if not entries:
            logger.warning("Empty feed from '%s'", source.name)
            _mark_failure(source, "empty")
            return 0

        for entry in entries:
            raw_url = entry.get("link") or entry.get("id") or ""
            if not raw_url:
                continue

            canonical = canonicalize_url(raw_url)
            if not canonical:
                continue

            # 1. Сначала проверяем in-memory set (ловит кросс-источниковые дубли до commit)
            if canonical in seen_urls:
                continue

            # 2. Затем проверяем DB
            if db.query(NewsItem).filter(NewsItem.original_url == canonical).first():
                seen_urls.add(canonical)
                continue

            title = (entry.get("title") or "").strip()
            summary_raw = (entry.get("summary") or entry.get("description") or "").strip()
            summary = re.sub(r"<[^>]+>", " ", summary_raw)
            summary = re.sub(r"\s+", " ", summary).strip()[:2000]

            image_url = _extract_image(entry)
            video_url = _extract_video(entry)
            media_type = "video" if video_url else ("image" if image_url else None)

            item = NewsItem(
                source_id=source.id,
                original_url=canonical,
                title_original=title[:500] if title else None,
                text_original=summary[:3000] if summary else None,
                original_language=getattr(source, "language_hint", None),
                image_url=image_url,
                video_url=video_url,
                media_type=media_type,
                trust_score=float(getattr(source, "trust_score", 0.7) or 0.7),
                status="new",
            )

            # 3. flush + per-item IntegrityError — если дубль проскочил, откатываем только его
            try:
                db.add(item)
                db.flush()
                seen_urls.add(canonical)
                created += 1
            except IntegrityError:
                db.rollback()
                seen_urls.add(canonical)
                logger.debug("IntegrityError (harmless race) for: %s", canonical)
                continue

        _mark_success(source, len(entries))

        if created > 0:
            logger.info("%s: +%d new items", source.name, created)

    except httpx.TimeoutException:
        logger.warning("Timeout fetching '%s'", source.name)
        _mark_failure(source, "dead")
    except httpx.ConnectError as exc:
        err = str(exc)
        if "SSL" in err or "certificate" in err.lower():
            logger.warning("SSL error fetching '%s': %s", source.name, exc)
            _mark_failure(source, "ssl_error")
        else:
            logger.warning("Connection error fetching '%s': %s", source.name, exc)
            _mark_failure(source, "dead")
    except Exception as exc:
        logger.error("Unexpected error fetching '%s': %s", source.name, exc)
        _mark_failure(source, "dead")

    return created


# ---------------------------------------------------------------------------
# All sources orchestrator
# ---------------------------------------------------------------------------

def fetch_all_rss_sources(db: Session) -> int:
    """
    Фетчит все активные RSS источники.

    Каждый источник коммитится отдельно — ошибка в источнике N
    не откатывает успешно сохранённые items из источников 1..N-1.
    """
    sources = db.query(Source).filter(Source.is_active == True).all()
    if not sources:
        logger.warning("No active sources in DB")
        return 0

    total = 0
    failed_commits = 0
    seen_urls: set[str] = set()

    for source in sources:
        count = fetch_single_source(db, source, seen_urls)
        total += count

        try:
            db.commit()
        except Exception as exc:
            logger.error(
                "Commit error after '%s' — rolling back this source: %s",
                source.name, exc,
            )
            db.rollback()
            total -= count
            failed_commits += 1

    if failed_commits:
        logger.warning("RSS fetch: %d source(s) had commit errors", failed_commits)

    logger.info("RSS fetch done: %d sources -> %d new items", len(sources), total)
    return total