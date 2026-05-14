"""
Build Posts task — constructs pending Post records from processed NewsItems.

Rules:
 - publish only fully rewritten RU items
 - skip low-quality / empty rewrites
 - deduplicate per cluster
 - protect against duplicate Post rows
"""
from __future__ import annotations

import json
import re

from sqlalchemy.exc import IntegrityError

from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.channel import Channel
from app.models.news_item import NewsItem
from app.models.post import Post
from app.models.source import Source
from app.posting.formatter import build_post_html
from app.processing.moderation_router import ModerationDecision, decide_moderation

logger = setup_logger("build_posts")

MAX_POSTS_PER_RUN = 50
MAX_PER_CHANNEL = 20
FETCH_LIMIT = 800

_SPORT_RE = [
    r"\bспорт\b", r"\bматч\b", r"\bгол\b", r"\bчемпионат\b", r"\bлига\b",
    r"\bфутбол", r"\bхоккей", r"\bтеннис", r"\bpremier league\b",
    r"\bформул[аы][- ]?1\b",
]
_TECH_TITLE_RE = [
    r"^h15:", r"^h41:", r"^z1:", r"^g17:", r"^g20:", r"^cp:",
    r"\bdata download\b", r"\bselected interest rates\b",
]
_BAD_URL_RE = [
    r"/sport/", r"/sports/", r"/video/", r"/videos/", r"/photoslider/",
    # CBR технические страницы с историческими данными
    r"/pffl", r"/dirrepo", r"/UniDbQuery", r"/File/90134",
    r"/hd_base/", r"/statistics/pffl",
]


def _lower(v: str | None) -> str:
    return (v or "").strip().lower()


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _is_good_image_url(url: str | None) -> bool:
    u = _lower(url)
    if not u or not (u.startswith("http://") or u.startswith("https://")):
        return False
    bad = ["placeholder", "default-image", "no-image", "spacer", "pixel", "blank.gif", "1x1", "transparent"]
    return not any(x in u for x in bad)


def _is_good_video_url(url: str | None) -> bool:
    u = _lower(url)
    return bool(u and (u.startswith("http://") or u.startswith("https://")))


def _source_name(source_map: dict, source_id: int | None) -> str:
    s = source_map.get(source_id) if source_id else None
    return (getattr(s, "name", None) or "").strip() or "Источник"


def _quick_filter(item: NewsItem) -> tuple[bool, str]:
    title_blob = _lower(item.title_ru or item.title_original)
    url = _lower(item.original_url)

    if _matches_any(title_blob, _SPORT_RE):
        return True, "sport_title"
    if _matches_any(title_blob, _TECH_TITLE_RE):
        return True, "tech_title"
    if _matches_any(url, _BAD_URL_RE):
        return True, "bad_url"

    safe_title = (item.title_ru or "").strip()
    safe_summary = (item.summary_ru or "").strip()

    if not safe_title or not safe_summary:
        return True, "missing_ru_rewrite"
    if len(safe_title) < 12:
        return True, "title_ru_too_short"
    if len(safe_summary) < 140:
        return True, "summary_ru_too_short"

    return False, ""


def main() -> None:
    db = SessionLocal()
    try:
        channels = db.query(Channel).all()
        channel_map_by_code = {c.category_code: c for c in channels if c.category_code}

        if not channels:
            logger.warning("No channels configured in DB")
            return

        from datetime import datetime, timedelta, timezone
        # Только свежие новости (не старше 24 часов)
        freshness_cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)

        items = (
            db.query(NewsItem)
            .filter(
                NewsItem.rewrite_status == "done",
                NewsItem.is_duplicate == False,
                NewsItem.is_relevant == True,
                NewsItem.category.is_not(None),
                NewsItem.category != "discard",
                NewsItem.status == "ready",
                NewsItem.fetched_at >= freshness_cutoff,  # только свежие
            )
            .order_by(NewsItem.importance_score.desc(), NewsItem.fetched_at.desc())
            .limit(FETCH_LIMIT)
            .all()
        )

        logger.info("build_posts: %d candidate items", len(items))

        source_ids = {i.source_id for i in items if i.source_id}
        sources = db.query(Source).filter(Source.id.in_(source_ids)).all()
        source_map = {s.id: s for s in sources}

        posts_per_channel: dict[int, int] = {}
        cluster_ids_used: set[str] = set()
        total_created = 0

        skip_stats = {
            "quick_filter": 0,
            "cluster_used": 0,
            "no_channel": 0,
            "channel_limit": 0,
            "already_exists": 0,
            "discarded_by_moderation": 0,
            "integrity_duplicates": 0,
        }
        quick_filter_reasons: dict[str, int] = {}

        for item in items:
            if total_created >= MAX_POSTS_PER_RUN:
                break

            safe_title = (item.title_ru or "").strip()
            safe_summary = (item.summary_ru or "").strip()

            should_skip, reason = _quick_filter(item)
            if should_skip:
                skip_stats["quick_filter"] += 1
                quick_filter_reasons[reason] = quick_filter_reasons.get(reason, 0) + 1
                continue

            if item.cluster_id and item.cluster_id in cluster_ids_used:
                skip_stats["cluster_used"] += 1
                continue

            category = (item.category or "world").lower()
            channel = channel_map_by_code.get(category) or channel_map_by_code.get("world") or (channels[0] if channels else None)

            if not channel:
                skip_stats["no_channel"] += 1
                continue

            ch_count = posts_per_channel.get(channel.id, 0)
            if ch_count >= MAX_PER_CHANNEL:
                skip_stats["channel_limit"] += 1
                continue

            existing = (
                db.query(Post)
                .filter(Post.news_id == item.id, Post.channel_id == channel.id)
                .first()
            )
            if existing:
                skip_stats["already_exists"] += 1
                continue

            source = source_map.get(item.source_id)
            trust = float(getattr(source, "trust_score", 0.70) or 0.70)
            source_type = getattr(source, "source_type", "rss")

            mod_result = decide_moderation(
                title_ru=safe_title,
                summary_ru=safe_summary,
                category=item.category,
                classification_confidence=float(item.routing_confidence or 0.5),
                trust_score=trust,
                quality_score=int(item.quality_score or 0),
                original_url=item.original_url,
                is_duplicate=bool(item.is_duplicate),
                source_type=source_type,
            )

            if mod_result.decision == ModerationDecision.DISCARD:
                item.status = "filtered"
                item.moderation_decision = mod_result.decision.value
                item.moderation_reason = mod_result.reason
                item.moderation_flags = json.dumps(mod_result.flags, ensure_ascii=False) if mod_result.flags else None
                skip_stats["discarded_by_moderation"] += 1
                continue

            src_name = _source_name(source_map, item.source_id)
            post_html = build_post_html(
                title_ru=safe_title,
                summary_ru=safe_summary,
                source_name=src_name,
                category=item.category,
                original_url=item.original_url,
                channel_code=category,
                why_important_ru=item.why_important_ru,
                market_impact_ru=item.market_impact_ru,
                quote_ru=item.quote_ru,
            )

            if _is_good_video_url(item.video_url):
                post_type = "video"
            elif _is_good_image_url(item.image_url):
                post_type = "photo"
            else:
                post_type = "text"

            item.moderation_decision = mod_result.decision.value
            item.moderation_reason = mod_result.reason
            item.moderation_flags = json.dumps(mod_result.flags, ensure_ascii=False) if mod_result.flags else None

            post_status = "pending_moderation" if mod_result.decision == ModerationDecision.SEND_TO_MODERATION else "pending"

            post = Post(
                news_id=item.id,
                channel_id=channel.id,
                post_type=post_type,
                post_text_html=post_html,
                status=post_status,
            )

            try:
                db.add(post)
                db.flush()
            except IntegrityError:
                db.rollback()
                skip_stats["integrity_duplicates"] += 1
                continue

            item.status = "post_created"
            posts_per_channel[channel.id] = ch_count + 1
            if item.cluster_id:
                cluster_ids_used.add(item.cluster_id)
            total_created += 1

        db.commit()
        logger.info("build_posts: created %d posts", total_created)
        logger.info("build_posts: skip_stats=%s", skip_stats)
        if quick_filter_reasons:
            logger.info("build_posts: quick_filter_reasons=%s", quick_filter_reasons)

    finally:
        db.close()


if __name__ == "__main__":
    main()