from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.channel import Channel
from app.models.news_item import NewsItem
from app.models.post import Post
from app.models.source import Source


logger = setup_logger("update_post_types")


def main() -> None:
    db = SessionLocal()
    try:
        news_map = {item.id: item for item in db.query(NewsItem).all()}

        posts = (
            db.query(Post)
            .filter(Post.status.in_(["pending", "on_moderation"]))
            .all()
        )

        updated_count = 0

        for post in posts:
            news_item = news_map.get(post.news_id)
            if not news_item:
                continue

            new_post_type = "photo" if news_item.image_url else "text"

            if post.post_type != new_post_type:
                post.post_type = new_post_type
                updated_count += 1

        db.commit()
        logger.info("Updated post_type for posts: %s", updated_count)
        print(f"Обновлено post_type у постов: {updated_count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()