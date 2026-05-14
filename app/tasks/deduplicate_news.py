"""
Deduplication task — multi-level story deduplication.

Levels (applied in order):
  1. Exact URL match (already unique=True in DB, handled at ingest)
  2. Near-duplicate title (fuzzy ratio ≥ 88)
  3. Story cluster (title+summary token overlap ≥ 60%)

For each duplicate group: keep best primary source, mark others as duplicate.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.news_item import NewsItem
from app.models.source import Source
from app.processing.deduplicator import (
    are_same_story,
    are_titles_similar,
    canonicalize_url,
    pick_primary_source,
)

logger = setup_logger("deduplicate_news")

DEDUP_WINDOW_HOURS = 48
BATCH_LIMIT = 500


def _source_trust(source_map: dict[int, Source], source_id: int | None) -> float:
    s = source_map.get(source_id) if source_id else None
    return float(getattr(s, "trust_score", 0.5) or 0.5)


def _story_cluster_id(title: str | None, summary: str | None) -> str:
    """Deterministic cluster ID from normalized title tokens."""
    from app.processing.deduplicator import normalize_title, title_tokens

    tokens = sorted(title_tokens(title))
    key = " ".join(tokens[:8])  # Top-8 tokens as cluster anchor
    return hashlib.md5(key.encode()).hexdigest()[:12]


def main() -> None:
    db = SessionLocal()
    try:
        # Берём только свежие (48 часов) — дедупликация устаревших бессмысленна
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=DEDUP_WINDOW_HOURS)

        items = (
            db.query(NewsItem)
            .filter(
                NewsItem.fetched_at >= cutoff,
                NewsItem.is_duplicate == False,
                NewsItem.category.is_not(None),
                NewsItem.category != "discard",
            )
            .order_by(NewsItem.fetched_at.asc())
            .limit(BATCH_LIMIT)
            .all()
        )

        if not items:
            logger.info("Dedup: no items to process")
            return

        source_ids = {i.source_id for i in items if i.source_id}
        sources = db.query(Source).filter(Source.id.in_(source_ids)).all()
        source_map = {s.id: s for s in sources}

        logger.info("Dedup: processing %d items (window=%dh)", len(items), DEDUP_WINDOW_HOURS)

        marked = 0
        clustered = 0

        # Build processed list: [(item, cluster_id)]
        processed: list[tuple[NewsItem, str]] = []

        for item in items:
            cluster_id = _story_cluster_id(item.title_ru or item.title_original, item.summary_ru)

            found_duplicate = False

            for prev_item, prev_cluster in processed:
                # Level 1: exact cluster ID
                if cluster_id == prev_cluster and cluster_id:
                    # Same cluster — now compare quality to pick primary
                    item_meta = {
                        "trust_score": _source_trust(source_map, item.source_id),
                        "text_length": len(item.text_original or ""),
                        "has_image": bool(item.image_url),
                        "has_video": bool(item.video_url),
                    }
                    prev_meta = {
                        "trust_score": _source_trust(source_map, prev_item.source_id),
                        "text_length": len(prev_item.text_original or ""),
                        "has_image": bool(prev_item.image_url),
                        "has_video": bool(prev_item.video_url),
                    }
                    primary = pick_primary_source(prev_meta, item_meta)
                    if primary == "b":
                        # Current item is better — demote previous
                        prev_item.is_duplicate = True
                        prev_item.cluster_id = cluster_id
                        prev_item.is_primary_in_cluster = False
                        item.cluster_id = cluster_id
                        item.is_primary_in_cluster = True
                    else:
                        # Previous is better — mark current as duplicate
                        item.is_duplicate = True
                        item.cluster_id = cluster_id
                        item.is_primary_in_cluster = False
                    found_duplicate = True
                    marked += 1
                    break

                # Level 2: near-duplicate title
                if are_titles_similar(
                    item.title_ru or item.title_original,
                    prev_item.title_ru or prev_item.title_original,
                ):
                    item.is_duplicate = True
                    item.cluster_id = prev_cluster or _story_cluster_id(
                        prev_item.title_ru or prev_item.title_original,
                        prev_item.summary_ru,
                    )
                    item.is_primary_in_cluster = False
                    found_duplicate = True
                    marked += 1
                    break

                # Level 3: story cluster (broader match)
                if are_same_story(
                    item.title_ru or item.title_original,
                    item.summary_ru,
                    prev_item.title_ru or prev_item.title_original,
                    prev_item.summary_ru,
                ):
                    shared_cluster = prev_cluster or cluster_id
                    item.is_duplicate = True
                    item.cluster_id = shared_cluster
                    item.is_primary_in_cluster = False
                    # Make sure prev has a cluster ID too
                    if not prev_item.cluster_id:
                        prev_item.cluster_id = shared_cluster
                    found_duplicate = True
                    clustered += 1
                    marked += 1
                    break

            if not found_duplicate:
                item.cluster_id = cluster_id
                item.is_primary_in_cluster = True

            processed.append((item, cluster_id))

        db.commit()
        logger.info(
            "Dedup done: %d/%d marked as duplicates (story clusters: %d)",
            marked,
            len(items),
            clustered,
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()