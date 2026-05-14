"""
Main entry point — initializes DB, seeds sources and channels, starts scheduler + bot.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from app.bot.moderation_bot import router as moderation_router
from app.core.config import settings
from app.core.logger import setup_logger
from app.db.init_db import init as init_db
from app.db.seed_channels import seed as seed_channels
from app.db.seed_sources import seed as seed_sources
from app.db.session import SessionLocal
from app.tasks.pipeline import run_processing_pipeline
from app.tasks.scheduler import start_scheduler

logger = setup_logger("main")


async def on_startup(bot: Bot) -> None:
    logger.info("Bot started — running initial pipeline...")
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, run_processing_pipeline)
    except Exception as e:
        logger.error("Initial pipeline failed: %s", e)


async def main() -> None:
    # 1. Initialize database
    logger.info("Initializing database...")
    init_db()

    # 2. Seed channels and sources
    db = SessionLocal()
    try:
        seed_channels(db)
        seed_sources(db)
    finally:
        db.close()

    # 3. Start background scheduler
    scheduler = start_scheduler()

    # 4. Start bot
    from aiogram.client.default import DefaultBotProperties
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(moderation_router)
    dp.startup.register(on_startup)

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=["callback_query", "message"])
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
