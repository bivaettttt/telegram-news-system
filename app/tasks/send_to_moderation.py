"""
Send-to-moderation task — routes flagged posts to the moderation chat.

Only posts with status='pending_moderation' are processed here.
Normal posts (status='pending') are published directly by publish_posts.

Moderation message includes:
 - Post content
 - Moderation reason + flags
 - Approve / Reject / Channel buttons
"""
from __future__ import annotations

import asyncio
import json

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from app.bot.moderation_bot import build_moderation_keyboard
from app.core.config import settings
from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.channel import Channel
from app.models.news_item import NewsItem
from app.models.post import Post
from app.processing.moderation_router import format_moderation_message

logger = setup_logger("send_to_moderation")

MAX_PER_BATCH = 8
INTER_MSG_DELAY = 1.0


async def main() -> None:
    if not settings.moderation_chat_id:
        logger.debug("No moderation_chat_id configured — skipping")
        return

    db = SessionLocal()
    async with Bot(token=settings.bot_token) as bot:
        try:
            channels = db.query(Channel).all()
            channel_map = {c.id: c for c in channels}

            pending = (
                db.query(Post)
                .filter(Post.status == "pending_moderation")
                .order_by(Post.id.asc())
                .limit(MAX_PER_BATCH)
                .all()
            )

            if not pending:
                logger.debug("No posts pending moderation")
                return

            news_ids = [p.news_id for p in pending]
            news_items = db.query(NewsItem).filter(NewsItem.id.in_(news_ids)).all()
            news_map = {n.id: n for n in news_items}

            sent = 0

            for post in pending:
                channel = channel_map.get(post.channel_id)
                channel_name = getattr(channel, "name", "Unknown") if channel else "Unknown"
                news = news_map.get(post.news_id)

                # Build reason string from stored flags
                reason = "—"
                if news and news.moderation_reason:
                    reason = news.moderation_reason
                flags: list[str] = []
                if news and news.moderation_flags:
                    try:
                        flags = json.loads(news.moderation_flags)
                    except Exception:
                        pass

                from app.processing.moderation_router import ModerationResult, ModerationDecision
                mod_result = ModerationResult(
                    decision=ModerationDecision.SEND_TO_MODERATION,
                    reason=reason,
                    confidence=float(getattr(news, "routing_confidence", 0.5) or 0.5),
                    flags=flags,
                )

                msg_text = format_moderation_message(
                    post_id=post.id,
                    channel_name=channel_name,
                    post_text_html=post.post_text_html or "",
                    moderation_result=mod_result,
                )

                keyboard = build_moderation_keyboard(post_id=post.id)

                try:
                    await bot.send_message(
                        chat_id=settings.moderation_chat_id,
                        text=msg_text[:4096],
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                    post.status = "in_moderation"
                    sent += 1
                except TelegramAPIError as e:
                    logger.error("Moderation send error post_id=%d: %s", post.id, e)
                    # Don't block — mark as error to avoid loop
                    post.status = "moderation_error"

                await asyncio.sleep(INTER_MSG_DELAY)

            db.commit()
            logger.info("Sent %d posts to moderation", sent)

        finally:
            db.close()


if __name__ == "__main__":
    asyncio.run(main())
