"""
Initialize the database — creates all tables.
Safe to run multiple times (uses CREATE TABLE IF NOT EXISTS).
"""
from app.core.logger import setup_logger
from app.db.session import Base, engine
from app.models import channel, news_item, post, source  # noqa: F401 — registers models

logger = setup_logger("init_db")


def init() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created (or already exist)")
    print("✓ DB initialized")


if __name__ == "__main__":
    init()
