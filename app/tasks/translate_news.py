from app.db.session import SessionLocal
from app.models.channel import Channel
from app.models.news_item import NewsItem
from app.models.post import Post
from app.models.source import Source
from app.translation.translator import normalize_russian_fields


def main() -> None:
    db = SessionLocal()
    try:
        news_items = (
            db.query(NewsItem)
            .filter(
                (NewsItem.title_ru.is_(None)) | (NewsItem.title_ru == "")
            )
            .all()
        )

        updated_count = 0

        for item in news_items:
            title_ru, summary_ru = normalize_russian_fields(
                original_language=item.original_language,
                title_original=item.title_original,
                text_original=item.text_original,
            )

            item.title_ru = title_ru
            item.summary_ru = summary_ru
            updated_count += 1

        db.commit()
        print(f"Переведено/заполнено новостей: {updated_count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()