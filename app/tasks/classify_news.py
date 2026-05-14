"""
Classification task — assigns category + routing confidence to raw news items.

Writes to:
  - news_item.category
  - news_item.routing_confidence
  - news_item.routing_reason
"""
from __future__ import annotations

from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.news_item import NewsItem
from app.models.source import Source
from app.processing.classifier import classify_news_detailed

logger = setup_logger("classify_news")

BATCH_LIMIT = 300


def main() -> None:
    db = SessionLocal()
    try:
        items = (
            db.query(NewsItem)
            .filter(NewsItem.category == None, NewsItem.status != "published")
            .order_by(NewsItem.fetched_at.desc())
            .limit(BATCH_LIMIT)
            .all()
        )

        if not items:
            logger.debug("No unclassified items")
            return

        # Pre-load sources for category hints
        source_ids = {i.source_id for i in items if i.source_id}
        sources = db.query(Source).filter(Source.id.in_(source_ids)).all()
        source_map = {s.id: s for s in sources}

        classified = 0
        discarded = 0

        for item in items:
            source = source_map.get(item.source_id) if item.source_id else None
            source_hint = getattr(source, "category_hint", None) if source else None
            source_name = getattr(source, "name", None) if source else None

            result = classify_news_detailed(
                title=item.title_ru or item.title_original,
                text=item.summary_ru or item.text_original,
                source_name=source_name,
                source_category_hint=source_hint,
            )

            item.category = result.category
            item.routing_confidence = result.confidence
            item.routing_reason = "; ".join(result.reasons) if result.reasons else None

            if result.category == "discard":
                item.status = "filtered"
                item.is_relevant = False
                discarded += 1
            else:
                classified += 1

        db.commit()
        logger.info(
            "Classify: processed %d items — classified=%d discarded=%d",
            len(items), classified, discarded,
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()
