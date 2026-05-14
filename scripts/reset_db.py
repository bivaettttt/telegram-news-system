"""
Скрипт управления базой данных.

Использование:
    python scripts/reset_db.py --help
    python scripts/reset_db.py --clear-stale        # удалить устаревшие записи (>36ч)
    python scripts/reset_db.py --reset-pending      # сбросить застрявшие в pending
    python scripts/reset_db.py --clear-all          # ПОЛНАЯ очистка (осторожно!)
    python scripts/reset_db.py --status             # показать статистику
    python scripts/reset_db.py --clear-cbr          # удалить технические данные ЦБ РФ
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db.session import SessionLocal


def show_status(db) -> None:
    row = db.execute(text("""
        SELECT
          (SELECT COUNT(*) FROM news_items) AS total_news,
          (SELECT COUNT(*) FROM news_items WHERE status = 'new') AS news_new,
          (SELECT COUNT(*) FROM news_items WHERE status = 'ready') AS news_ready,
          (SELECT COUNT(*) FROM news_items WHERE status = 'filtered') AS news_filtered,
          (SELECT COUNT(*) FROM news_items WHERE status = 'published') AS news_published,
          (SELECT COUNT(*) FROM news_items WHERE status = 'post_created') AS news_post_created,
          (SELECT COUNT(*) FROM news_items WHERE rewrite_status = 'pending') AS rw_pending,
          (SELECT COUNT(*) FROM news_items WHERE rewrite_status = 'retry') AS rw_retry,
          (SELECT COUNT(*) FROM news_items WHERE rewrite_status = 'error') AS rw_error,
          (SELECT COUNT(*) FROM posts) AS total_posts,
          (SELECT COUNT(*) FROM posts WHERE status = 'pending') AS posts_pending,
          (SELECT COUNT(*) FROM posts WHERE status = 'published') AS posts_pub,
          (SELECT COUNT(*) FROM posts WHERE status = 'error') AS posts_err,
          (SELECT MIN(fetched_at) FROM news_items) AS oldest_item,
          (SELECT MAX(fetched_at) FROM news_items) AS newest_item
    """)).fetchone()

    print("\n=== DATABASE STATUS ===")
    print(f"News items total:     {row.total_news}")
    print(f"  new:                {row.news_new}")
    print(f"  ready:              {row.news_ready}")
    print(f"  post_created:       {row.news_post_created}")
    print(f"  published:          {row.news_published}")
    print(f"  filtered:           {row.news_filtered}")
    print(f"Rewrite queue:")
    print(f"  pending:            {row.rw_pending}")
    print(f"  retry:              {row.rw_retry}")
    print(f"  error:              {row.rw_error}")
    print(f"Posts total:          {row.total_posts}")
    print(f"  pending:            {row.posts_pending}")
    print(f"  published:          {row.posts_pub}")
    print(f"  error:              {row.posts_err}")
    print(f"Oldest item:          {row.oldest_item}")
    print(f"Newest item:          {row.newest_item}")
    print()


def clear_stale(db, hours: int = 36) -> None:
    """Удалить/отфильтровать записи старше N часов."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    cutoff_str = cutoff.isoformat()

    result = db.execute(text("""
        UPDATE news_items
        SET status = 'filtered', rewrite_status = 'error'
        WHERE fetched_at < :cutoff
          AND status NOT IN ('published', 'filtered')
    """), {"cutoff": cutoff_str})
    db.commit()
    print(f"Marked {result.rowcount} items older than {hours}h as filtered.")


def clear_cbr_technical(db) -> None:
    """Удалить технические страницы ЦБ РФ (статистика, таблицы)."""
    patterns = ["/pffl", "/dirrepo", "/UniDbQuery", "/File/90134", "/hd_base/"]
    total = 0
    for p in patterns:
        result = db.execute(text("""
            UPDATE news_items
            SET status = 'filtered', rewrite_status = 'error'
            WHERE original_url LIKE :pattern
              AND status != 'published'
        """), {"pattern": f"%{p}%"})
        if result.rowcount:
            print(f"  Pattern '{p}': filtered {result.rowcount} items")
            total += result.rowcount
    db.commit()
    print(f"CBR technical pages: filtered {total} items total.")


def reset_pending(db) -> None:
    """Сбросить застрявшие в 'new'/'ready' записи обратно в очередь."""
    result = db.execute(text("""
        UPDATE news_items
        SET rewrite_status = 'pending'
        WHERE rewrite_status IN ('retry', 'error')
          AND status = 'new'
          AND fetched_at >= NOW() - INTERVAL '36 hours'
    """))
    db.commit()
    print(f"Reset {result.rowcount} items from retry/error → pending (fresh only).")


def clear_all(db) -> None:
    """ПОЛНАЯ очистка всех новостей и постов."""
    print("⚠️  WARNING: This will delete ALL news items and posts!")
    confirm = input("Type 'yes' to confirm: ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    db.execute(text("DELETE FROM posts"))
    db.execute(text("DELETE FROM news_items"))
    db.commit()
    print("✓ All news items and posts deleted.")
    print("  The bot will start fresh on next pipeline run.")


def main() -> None:
    parser = argparse.ArgumentParser(description="News Bot DB Management")
    parser.add_argument("--status", action="store_true", help="Show DB statistics")
    parser.add_argument("--clear-stale", action="store_true", help="Filter items older than 36h")
    parser.add_argument("--clear-cbr", action="store_true", help="Filter CBR technical pages")
    parser.add_argument("--reset-pending", action="store_true", help="Reset retry/error items → pending")
    parser.add_argument("--clear-all", action="store_true", help="Delete ALL items (requires confirmation)")
    parser.add_argument("--hours", type=int, default=36, help="Hours threshold for --clear-stale (default: 36)")
    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        return

    db = SessionLocal()
    try:
        if args.status:
            show_status(db)
        if args.clear_stale:
            clear_stale(db, args.hours)
        if args.clear_cbr:
            clear_cbr_technical(db)
        if args.reset_pending:
            reset_pending(db)
        if args.clear_all:
            clear_all(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
