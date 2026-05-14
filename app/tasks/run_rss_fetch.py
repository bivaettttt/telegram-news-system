from app.db.session import SessionLocal
from app.sources.rss_fetcher import fetch_all_rss_sources


def main() -> None:
    db = SessionLocal()
    try:
        total_created = fetch_all_rss_sources(db)
        print(f"Всего добавлено новостей: {total_created}")
    finally:
        db.close()


if __name__ == "__main__":
    main()