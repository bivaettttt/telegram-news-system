"""
Seed channels — creates World and Economy channels in the DB.

Also creates legacy channels if their IDs are configured in .env.
Safe to re-run: skips existing channels.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.channel import Channel

logger = setup_logger("seed_channels")


def seed(db: Session) -> None:
    # Core channels — always required
    core_channels = [
        {
            "name": "World",
            "code": "world",
            "telegram_chat_id": settings.channel_world_id,
        },
        {
            "name": "Economy",
            "code": "economy",
            "telegram_chat_id": settings.channel_economy_id,
        },
    ]

    # Legacy / optional channels
    if settings.channel_russia_id:
        core_channels.append({
            "name": "Russia",
            "code": "russia",
            "telegram_chat_id": settings.channel_russia_id,
        })

    added = 0
    for ch in core_channels:
        if not ch.get("telegram_chat_id"):
            continue
        existing = db.query(Channel).filter(Channel.telegram_chat_id == ch["telegram_chat_id"]).first()
        if existing:
            # Update name/code if changed
            existing.name = ch["name"]
            if hasattr(existing, "code"):
                existing.code = ch["code"]
            elif hasattr(existing, "category_code"):
                existing.category_code = ch["code"]
            continue
        channel = Channel(
            name=ch["name"],
            telegram_chat_id=ch["telegram_chat_id"],
            is_active=True,
        )
        # Support both `code` and legacy `category_code` column names
        if hasattr(Channel, "code"):
            channel.code = ch["code"]
        if hasattr(Channel, "category_code"):
            channel.category_code = ch["code"]
        db.add(channel)
        added += 1

    db.commit()
    if added:
        logger.info("seed_channels: %d channels added", added)
    print(f"✓ Channels seeded ({added} new)")


def main() -> None:
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
