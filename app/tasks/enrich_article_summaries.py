"""
Enrichment task — fills text_original and image_url for newly fetched items.

Uses trafilatura for full-text extraction and OG image extraction.
Runs before classify/rewrite so those tasks have full content to work with.
"""
from __future__ import annotations

import asyncio

import trafilatura

from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.media.downloader import extract_og_image, is_supported_image_url, score_image_url
from app.models.news_item import NewsItem

logger = setup_logger("enrich")

BATCH_LIMIT = 80
FETCH_TIMEOUT = 20


def _fetch_full_text(url: str) -> str | None:
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        return text
    except Exception:
        return None


async def _enrich_one(item: NewsItem) -> None:
    """Enrich a single item: full text + best image."""
    # Only fetch full text if we don't already have decent content
    current_text = (item.text_original or "").strip()
    if len(current_text) < 200:
        text = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_full_text, item.original_url
        )
        if text and len(text) > len(current_text):
            item.text_original = text[:8000]  # Cap at 8k chars for DB

    # Enrich image
    if not is_supported_image_url(item.image_url) or score_image_url(item.image_url) < 3:
        og_img = await extract_og_image(item.original_url, timeout=10)
        if og_img and score_image_url(og_img) > score_image_url(item.image_url):
            item.image_url = og_img


async def _enrich_batch(items: list[NewsItem]) -> None:
    sem = asyncio.Semaphore(6)

    async def _guarded(item):
        async with sem:
            try:
                await _enrich_one(item)
            except Exception as exc:
                logger.debug("Enrich failed for item %d: %s", item.id, exc)

    await asyncio.gather(*[_guarded(item) for item in items])


def main() -> None:
    db = SessionLocal()
    try:
        items = (
            db.query(NewsItem)
            .filter(NewsItem.status == "new")
            .order_by(NewsItem.fetched_at.desc())
            .limit(BATCH_LIMIT)
            .all()
        )

        if not items:
            logger.debug("No items to enrich")
            return

        logger.info("Enriching %d items...", len(items))
        asyncio.run(_enrich_batch(items))
        db.commit()
        logger.info("Enrichment done for %d items", len(items))

    finally:
        db.close()


if __name__ == "__main__":
    main()
