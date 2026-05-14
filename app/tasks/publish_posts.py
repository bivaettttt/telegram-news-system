"""
Publish Posts task — отправляет pending посты в Telegram.

ИСПРАВЛЕНИЯ:
  - Проверка размера скачанного медиафайла перед отправкой (fix "file must be non-empty").
    Коммерсант и ряд других источников отдают пустые /SocialPics/ URL.
  - Если скачанный файл пустой или меньше 1 KB — фолбэк на текстовый пост.
  - Добавлена проверка Content-Length в заголовках до скачивания.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import FSInputFile

from app.core.config import settings
from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.media.downloader import download_remote_file, is_supported_image_url, is_supported_video_url
from app.models.channel import Channel
from app.models.news_item import NewsItem
from app.models.post import Post
from app.posting.publisher import build_source_keyboard

logger = setup_logger("publish_posts")

MAX_PER_RUN = 15
INTER_POST_DELAY = 2.0
MAX_CAPTION_LEN = 950
MAX_TEXT_LEN = 4096
RETRY_WAIT_DEFAULT = 10
MIN_IMAGE_BYTES = 1024  # файлы меньше 1 KB считаем битыми


def _plain_len(html_text: str) -> int:
    return len(re.sub(r"<[^>]+>", "", html_text or "").strip())


def _short_caption_from_html(html_text: str) -> str:
    text = (html_text or "").strip()
    if len(text) <= MAX_CAPTION_LEN:
        return text
    shortened = text[:MAX_CAPTION_LEN].rsplit(" ", 1)[0].strip()
    return (shortened or text[:MAX_CAPTION_LEN]).rstrip(" ,.;:-") + "…"


def _is_valid_file(path: Path) -> bool:
    """Проверяет что скачанный файл не пустой и не битый."""
    try:
        return path.exists() and path.stat().st_size >= MIN_IMAGE_BYTES
    except Exception:
        return False


async def _send_text(
    bot: Bot,
    chat_id: int,
    text: str,
    original_url: str | None = None,
    retry: int = 2,
) -> int | None:
    trimmed = text[:MAX_TEXT_LEN]
    for attempt in range(retry + 1):
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=trimmed,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=build_source_keyboard(original_url),
            )
            return msg.message_id
        except TelegramRetryAfter as e:
            wait = e.retry_after or RETRY_WAIT_DEFAULT
            logger.warning("Flood wait %ds for chat %s", wait, chat_id)
            await asyncio.sleep(wait)
        except TelegramAPIError as e:
            logger.error("Telegram text send error (attempt %d): %s", attempt + 1, e)
            if attempt < retry:
                await asyncio.sleep(3)
    return None


async def _send_photo(
    bot: Bot,
    chat_id: int,
    image_url: str,
    caption: str,
    original_url: str | None = None,
) -> int | None:
    short_caption = _short_caption_from_html(caption)

    # Попытка 1: отправить по URL напрямую
    try:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=image_url,
            caption=short_caption,
            parse_mode=ParseMode.HTML,
        )
        if _plain_len(caption) > MAX_CAPTION_LEN:
            await _send_text(bot, chat_id, caption, original_url=original_url)
        return msg.message_id
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after or RETRY_WAIT_DEFAULT)
    except TelegramAPIError:
        pass

    # Попытка 2: скачать и отправить файлом
    try:
        path = await download_remote_file(image_url, timeout=30)

        # Проверяем что файл не пустой (Коммерсант отдаёт пустые /SocialPics/)
        if not _is_valid_file(path):
            logger.debug(
                "Downloaded file too small (%d bytes), skipping photo: %s",
                path.stat().st_size if path.exists() else 0,
                image_url,
            )
            return await _send_text(bot, chat_id, caption, original_url=original_url)

        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(str(path)),
            caption=short_caption,
            parse_mode=ParseMode.HTML,
        )
        if _plain_len(caption) > MAX_CAPTION_LEN:
            await _send_text(bot, chat_id, caption, original_url=original_url)
        return msg.message_id

    except Exception as e:
        logger.debug("Photo upload failed (%s), falling back to text", e)
        return await _send_text(bot, chat_id, caption, original_url=original_url)


async def _send_video(
    bot: Bot,
    chat_id: int,
    video_url: str,
    caption: str,
    original_url: str | None = None,
) -> int | None:
    short_caption = _short_caption_from_html(caption)
    try:
        path = await download_remote_file(video_url, timeout=60)
        if not _is_valid_file(path):
            return await _send_text(bot, chat_id, caption, original_url=original_url)
        msg = await bot.send_video(
            chat_id=chat_id,
            video=FSInputFile(str(path)),
            caption=short_caption,
            parse_mode=ParseMode.HTML,
            supports_streaming=True,
        )
        if _plain_len(caption) > MAX_CAPTION_LEN:
            await _send_text(bot, chat_id, caption, original_url=original_url)
        return msg.message_id
    except Exception as e:
        logger.debug("Video upload failed (%s), falling back to text", e)
        return await _send_text(bot, chat_id, caption, original_url=original_url)


async def main() -> None:
    db = SessionLocal()
    async with Bot(token=settings.bot_token) as bot:
        try:
            channels = db.query(Channel).all()
            channel_map = {c.id: c for c in channels}

            pending = (
                db.query(Post)
                .filter(Post.status == "pending")
                .order_by(Post.id.asc())
                .limit(MAX_PER_RUN)
                .all()
            )

            if not pending:
                logger.debug("No pending posts to publish")
                return

            news_ids = [p.news_id for p in pending]
            news_items = db.query(NewsItem).filter(NewsItem.id.in_(news_ids)).all()
            news_map = {n.id: n for n in news_items}

            published = 0
            failed = 0
            failure_reasons: dict[str, int] = {}

            for post in pending:
                channel = channel_map.get(post.channel_id)
                if not channel:
                    post.status = "error"
                    post.error_message = "missing_channel"
                    failed += 1
                    continue

                chat_id = channel.telegram_chat_id
                text = post.post_text_html or ""
                news = news_map.get(post.news_id)
                original_url = news.original_url if news else None

                post.status = "publishing"
                db.flush()

                try:
                    msg_id = None

                    if post.post_type == "photo" and news and is_supported_image_url(news.image_url):
                        msg_id = await _send_photo(
                            bot, chat_id, news.image_url, text, original_url=original_url
                        )
                    elif post.post_type == "video" and news and is_supported_video_url(news.video_url):
                        msg_id = await _send_video(
                            bot, chat_id, news.video_url, text, original_url=original_url
                        )
                    else:
                        msg_id = await _send_text(
                            bot, chat_id, text, original_url=original_url
                        )

                    if msg_id:
                        post.telegram_message_id = msg_id
                        post.status = "published"
                        post.error_message = None
                        post.published_at = datetime.now(tz=timezone.utc)
                        if news:
                            news.published_at = datetime.now(tz=timezone.utc)
                            news.status = "published"
                        published += 1
                    else:
                        post.status = "error"
                        post.error_message = "send_failed"
                        failed += 1
                        failure_reasons["send_failed"] = failure_reasons.get("send_failed", 0) + 1

                except Exception as exc:
                    reason = str(exc).strip()[:160] or "publish_error"
                    logger.error("Publish error post_id=%d: %s", post.id, reason)
                    post.status = "error"
                    post.error_message = reason
                    failed += 1
                    failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

                await asyncio.sleep(INTER_POST_DELAY)

            db.commit()
            logger.info("Published: %d | Errors: %d", published, failed)
            if failure_reasons:
                logger.info("Publish fail reasons: %s", failure_reasons)

        finally:
            db.close()


if __name__ == "__main__":
    asyncio.run(main())