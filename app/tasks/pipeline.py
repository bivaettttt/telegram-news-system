"""
Main pipeline — оркестрирует все шаги обработки новостей.

Диагностика: _log_state() вызывается ДО и ПОСЛЕ шагов обработки.
Если что-то застряло — сразу видно на каком шаге.
"""
from __future__ import annotations

import asyncio
import time
import traceback

from sqlalchemy import text

from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.sources.rss_fetcher import fetch_all_rss_sources
from app.tasks.build_posts import main as build_posts_main
from app.tasks.classify_news import main as classify_news_main
from app.tasks.deduplicate_news import main as deduplicate_news_main
from app.tasks.enrich_article_summaries import main as enrich_main
from app.tasks.publish_posts import main as publish_main
from app.tasks.quality_check_news import main as quality_check_main
from app.tasks.rewrite_news import main as rewrite_main
from app.tasks.send_to_moderation import main as moderation_main

logger = setup_logger("pipeline")


def _run_step(name: str, fn) -> bool:
    t0 = time.monotonic()
    try:
        fn()
        logger.info("[pipeline] ✓ %s (%.1fs)", name, time.monotonic() - t0)
        return True
    except Exception:
        logger.error(
            "[pipeline] ✗ %s failed (%.1fs):\n%s",
            name, time.monotonic() - t0, traceback.format_exc(),
        )
        return False


async def _run_async_step(name: str, coro_fn) -> bool:
    t0 = time.monotonic()
    try:
        await coro_fn()
        logger.info("[pipeline] ✓ %s (%.1fs)", name, time.monotonic() - t0)
        return True
    except Exception:
        logger.error(
            "[pipeline] ✗ %s failed (%.1fs):\n%s",
            name, time.monotonic() - t0, traceback.format_exc(),
        )
        return False


def run_rss_fetch_step() -> int:
    db = SessionLocal()
    try:
        count = fetch_all_rss_sources(db)
        logger.info("[pipeline] fetch_rss: +%d new items", count)
        return count
    except Exception:
        logger.error("[pipeline] fetch_rss failed:\n%s", traceback.format_exc())
        return 0
    finally:
        db.close()


def _log_state(label: str = "") -> None:
    """
    Диагностический снимок очереди.
    Если всё стопится на 0 — видно на каком именно шаге.
    """
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM news_items WHERE status = 'new') AS news_new,
              (SELECT COUNT(*) FROM news_items
               WHERE category IS NULL
                 AND status NOT IN ('filtered','published','post_created')
              ) AS unclassified,
              (SELECT COUNT(*) FROM news_items
               WHERE rewrite_status IN ('pending','retry')
                 AND category IS NOT NULL AND category != 'discard'
                 AND status NOT IN ('filtered','published','post_created')
              ) AS pending_rewrite,
              (SELECT COUNT(*) FROM news_items
               WHERE rewrite_status = 'done'
                 AND status NOT IN ('filtered','published','post_created')
              ) AS rewrite_done,
              (SELECT COUNT(*) FROM news_items WHERE rewrite_status = 'error') AS rewrite_error,
              (SELECT COUNT(*) FROM news_items WHERE status = 'ready') AS news_ready,
              (SELECT COUNT(*) FROM news_items WHERE status = 'filtered') AS news_filtered,
              (SELECT COUNT(*) FROM posts WHERE status = 'pending') AS posts_pending,
              (SELECT COUNT(*) FROM posts WHERE status = 'pending_moderation') AS posts_mod,
              (SELECT COUNT(*) FROM posts WHERE status = 'published') AS posts_pub,
              (SELECT COUNT(*) FROM posts WHERE status = 'error') AS posts_err
        """)).fetchone()

        tag = f"[{label}] " if label else ""
        logger.info(
            "[pipeline] %sSTATE  "
            "new=%s unclassified=%s pending_rewrite=%s rewrite_done=%s rewrite_err=%s "
            "ready=%s filtered=%s  ||  "
            "posts: pending=%s mod=%s pub=%s err=%s",
            tag,
            row.news_new, row.unclassified, row.pending_rewrite,
            row.rewrite_done, row.rewrite_error,
            row.news_ready, row.news_filtered,
            row.posts_pending, row.posts_mod, row.posts_pub, row.posts_err,
        )
    finally:
        db.close()


def run_processing_pipeline() -> None:
    t_start = time.monotonic()
    logger.info("[pipeline] ═══ START ═══")

    fetched = run_rss_fetch_step()
    if fetched == 0:
        logger.info("[pipeline] No new items fetched; running downstream steps anyway")

    _log_state("before")

    _run_step("enrich",        enrich_main)
    _run_step("classify",      classify_news_main)
    _run_step("rewrite",       rewrite_main)
    _run_step("quality_check", quality_check_main)
    _run_step("deduplicate",   deduplicate_news_main)
    _run_step("build_posts",   build_posts_main)

    async def _async_steps():
        await _run_async_step("publish_posts",      publish_main)
        await _run_async_step("send_to_moderation", moderation_main)

    asyncio.run(_async_steps())

    _log_state("after")

    logger.info("[pipeline] ═══ DONE (%.1fs) ═══", time.monotonic() - t_start)


if __name__ == "__main__":
    run_processing_pipeline()