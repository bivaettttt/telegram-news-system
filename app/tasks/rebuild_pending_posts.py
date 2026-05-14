from app.db.session import SessionLocal
from app.models.channel import Channel
from app.models.news_item import NewsItem
from app.models.post import Post
from app.models.source import Source
from app.posting.formatter import build_post_html


def main() -> None:
    db = SessionLocal()
    try:
        news_map = {item.id: item for item in db.query(NewsItem).all()}
        source_map = {source.id: source for source in db.query(Source).all()}

        pending_posts = (
            db.query(Post)
            .filter(Post.status == "pending")
            .all()
        )

        updated_count = 0

        for post in pending_posts:
            news_item = news_map.get(post.news_id)
            if not news_item:
                continue

            source = source_map.get(news_item.source_id)
            source_name = source.name if source else "Неизвестный источник"

            new_post_html = build_post_html(
                title_ru=news_item.title_ru,
                summary_ru=news_item.summary_ru,
                source_name=source_name,
                category=news_item.category,
            )

            if post.post_text_html != new_post_html:
                post.post_text_html = new_post_html
                updated_count += 1

        db.commit()
        print(f"Обновлено pending-постов: {updated_count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()