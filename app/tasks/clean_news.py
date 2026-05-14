from app.db.session import SessionLocal
from app.models.news_item import NewsItem
from app.models.source import Source
from app.models.channel import Channel
from app.models.post import Post
from app.processing.cleaner import clean_html_text


def main() -> None:
    db = SessionLocal()
    try:
        news_items = db.query(NewsItem).all()

        updated_count = 0

        for item in news_items:
            cleaned_text = clean_html_text(item.text_original)
            if cleaned_text != (item.text_original or ""):
                item.text_original = cleaned_text
                updated_count += 1

        db.commit()
        print(f"Очищено новостей: {updated_count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()