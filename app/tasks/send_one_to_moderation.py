import asyncio
import sys

from aiogram import Bot

from app.bot.moderation_bot import build_moderation_keyboard
from app.core.config import settings
from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.channel import Channel
from app.models.news_item import NewsItem
from app.models.post import Post
from app.models.source import Source


logger = setup_logger("send_one_to_moderation")


def build_moderation_text(
    post_id: int,
    channel_name: str,
    post_text_html: str,
) -> str:
    return (
        f"<b>MODERATION</b>\n"
        f"<b>Post ID:</b> {post_id}\n"
        f"<b>Target channel:</b> {channel_name}\n\n"
        f"{post_text_html}"
    )


async def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python -m app.tasks.send_one_to_moderation <post_id>")
        return

    if not settings.moderation_chat_id:
        print("MODERATION_CHAT_ID не задан в .env")
        return

    try:
        post_id = int(sys.argv[1])
    except ValueError:
        print("post_id должен быть числом")
        return

    db = SessionLocal()
    async with Bot(token=settings.bot_token) as bot:
        try:
            post = db.query(Post).filter(Post.id == post_id).first()
            if not post:
                print(f"Пост id={post_id} не найден")
                return

            channel = db.query(Channel).filter(Channel.id == post.channel_id).first()
            if not channel:
                print(f"Канал для поста id={post_id} не найден")
                return

            moderation_text = build_moderation_text(
                post_id=post.id,
                channel_name=channel.name,
                post_text_html=post.post_text_html or "",
            )

            await bot.send_message(
                chat_id=settings.moderation_chat_id,
                text=moderation_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=build_moderation_keyboard(post.id),
            )

            post.status = "on_moderation"
            db.commit()

            logger.info("Sent post_id=%s to moderation", post_id)
            print(f"Пост {post_id} отправлен в модерацию")

        finally:
            db.close()


if __name__ == "__main__":
    asyncio.run(main())