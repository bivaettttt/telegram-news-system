from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db.session import Base


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("news_id", "channel_id", name="uq_posts_news_channel"),
    )

    id = Column(Integer, primary_key=True, index=True)
    news_id = Column(Integer, ForeignKey("news_items.id"), nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)

    telegram_message_id = Column(Integer, nullable=True)
    post_type = Column(String, nullable=False, default="text")
    post_text_html = Column(Text, nullable=True)

    status = Column(String, nullable=False, default="pending")
    error_message = Column(Text, nullable=True)

    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())