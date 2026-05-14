from __future__ import annotations

import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.session import engine
from sqlalchemy import text


def main() -> None:
    with engine.connect() as conn:
        print("=== news_items by status / rewrite_status ===")
        r = conn.execute(text("""
            SELECT status, rewrite_status, COUNT(*)
            FROM news_items
            GROUP BY status, rewrite_status
            ORDER BY COUNT(*) DESC
        """))
        for row in r:
            print(row)

        print("\n=== posts by status ===")
        r = conn.execute(text("""
            SELECT status, COUNT(*)
            FROM posts
            GROUP BY status
            ORDER BY COUNT(*) DESC
        """))
        for row in r:
            print(row)

        print("\n=== good RU rewrites ===")
        r = conn.execute(text("""
            SELECT COUNT(*)
            FROM news_items
            WHERE rewrite_status='done'
              AND title_ru IS NOT NULL AND TRIM(title_ru) != ''
              AND summary_ru IS NOT NULL AND TRIM(summary_ru) != ''
              AND is_relevant = true
              AND is_duplicate = false
              AND category IS NOT NULL
              AND category != 'discard'
        """))
        print("good_ru_news_items =", r.fetchone()[0])

        print("\n=== active / disabled sources ===")
        r = conn.execute(text("""
            SELECT is_active, health_status, COUNT(*)
            FROM sources
            GROUP BY is_active, health_status
            ORDER BY COUNT(*) DESC
        """))
        for row in r:
            print(row)

        print("\n=== top failing sources ===")
        r = conn.execute(text("""
            SELECT name, url, is_active, health_status, consecutive_failures
            FROM sources
            ORDER BY consecutive_failures DESC, name ASC
            LIMIT 20
        """))
        for row in r:
            print(row)


if __name__ == "__main__":
    main()