"""
Scheduler — APScheduler job runner.

Jobs:
  pipeline        — каждые 15 минут
  health_check    — каждые 6 часов
  cleanup         — ежедневно в 03:00 UTC
  retry_rewrites  — каждые 30 минут (сбрасывает retry/error→pending)
  retry_posts     — каждые 2 часа (сбрасывает failed posts→pending)
"""
from __future__ import annotations

import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logger import setup_logger
from app.tasks.pipeline import run_processing_pipeline

logger = setup_logger("scheduler")


def _run_pipeline() -> None:
    try:
        run_processing_pipeline()
    except Exception as e:
        logger.error("Scheduled pipeline failed: %s", e)


def _run_health_check() -> None:
    from app.tasks.check_sources_health import run_health_check
    try:
        asyncio.run(run_health_check())
    except Exception as e:
        logger.error("Scheduled health check failed: %s", e)


def _run_cleanup() -> None:
    """Удаляет медиафайлы старше 7 дней."""
    import time
    from pathlib import Path
    media_dir = Path("data/media")
    if not media_dir.exists():
        return
    cutoff = time.time() - 7 * 86400
    removed = 0
    for f in media_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    if removed:
        logger.info("Cleanup: removed %d stale media files", removed)


def _retry_failed_rewrites() -> None:
    """
    Возвращает rewrite_status='retry'|'error' (status='new') → 'pending'.

    Groq TPM лимит сбрасывается каждую минуту (скользящее окно).
    Запускаем каждые 30 мин — лимит точно сброшен к этому времени.
    Только свежие записи (не старше 6 часов) — старые уже неактуальны.
    """
    try:
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import update
        from app.db.session import SessionLocal
        from app.models.news_item import NewsItem

        db = SessionLocal()
        try:
            cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=6)
            result = db.execute(
                update(NewsItem)
                .where(
                    NewsItem.rewrite_status.in_(["retry", "error"]),
                    NewsItem.status == "new",
                    NewsItem.fetched_at >= cutoff,
                )
                .values(rewrite_status="pending")
            )
            db.commit()
            if result.rowcount:
                logger.info(
                    "Retry: reset %d rate-limited/error rewrites → pending",
                    result.rowcount,
                )
        finally:
            db.close()
    except Exception as e:
        logger.error("retry_failed_rewrites error: %s", e)


def _retry_failed_posts() -> None:
    """Возвращает posts.status='error' → 'pending' для повторной публикации."""
    try:
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import update
        from app.db.session import SessionLocal
        from app.models.post import Post

        db = SessionLocal()
        try:
            cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
            result = db.execute(
                update(Post)
                .where(
                    Post.status == "error",
                    Post.created_at >= cutoff,
                )
                .values(status="pending")
            )
            db.commit()
            if result.rowcount:
                logger.info("Retry: reset %d failed posts → pending", result.rowcount)
        finally:
            db.close()
    except Exception as e:
        logger.error("retry_failed_posts error: %s", e)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")

    scheduler.add_job(
        _run_pipeline,
        trigger=IntervalTrigger(minutes=15),
        id="pipeline",
        name="News pipeline",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _run_health_check,
        trigger=IntervalTrigger(hours=6),
        id="health_check",
        name="Source health check",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _run_cleanup,
        trigger=CronTrigger(hour=3, minute=0),
        id="cleanup",
        name="Media cache cleanup",
        max_instances=1,
    )

    scheduler.add_job(
        _retry_failed_rewrites,
        trigger=IntervalTrigger(minutes=30),
        id="retry_rewrites",
        name="Retry rate-limited rewrites",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _retry_failed_posts,
        trigger=IntervalTrigger(hours=2),
        id="retry_posts",
        name="Retry failed posts",
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — "
        "pipeline/15min | retry_rewrites/30min | retry_posts/2h | health/6h"
    )

    # Запускаем пайплайн сразу при старте — чтобы сегодняшние новости публиковались немедленно
    logger.info("Scheduler: running startup pipeline immediately...")
    import threading
    t = threading.Thread(target=_run_pipeline, daemon=True, name="startup-pipeline")
    t.start()

    return scheduler