import asyncio
import sys

from aiogram import Bot

from app.core.config import settings
from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.channel import Channel
from app.models.news_item import NewsItem
from app.models.post import Post
from app.models.source import Source
from app.posting.publisher import send_post


logger = setup_logger("publish_one_post")


async def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python -m app.tasks.publish_one_post <post_id>")
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
                print(f"Пост с id={post_id} не найден")
                return

            if post.status == "published":
                print(f"Пост id={post_id} уже опубликован")
                return

            channel = db.query(Channel).filter(Channel.id == post.channel_id).first()
            if not channel:
                print(f"Канал для поста id={post_id} не найден")
                return

            news_item = db.query(NewsItem).filter(NewsItem.id == post.news_id).first()
            if not news_item:
                print(f"Новость для поста id={post_id} не найдена")
                return

            telegram_message_id = await send_post(
                bot=bot,
                chat_id=channel.telegram_chat_id,
                post_text_html=post.post_text_html or "",
                original_url=news_item.original_url,
                image_url=news_item.image_url,
                video_url=news_item.video_url,
            )

            post.telegram_message_id = telegram_message_id
            post.status = "published"

            db.commit()
            logger.info(
                "Published post_id=%s to channel=%s, telegram_message_id=%s",
                post_id,
                channel.name,
                telegram_message_id,
            )
            print(
                f"Пост id={post_id} опубликован в канал '{channel.name}', "
                f"telegram_message_id={telegram_message_id}"
            )

        except Exception as exc:
            db.rollback()
            logger.exception("Publish one failed for post_id=%s: %s", post_id, exc)
            print(f"[PUBLISH ONE ERROR] {exc}")

        finally:
            db.close()


if __name__ == "__main__":
    asyncio.run(main())