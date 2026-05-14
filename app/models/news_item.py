from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class NewsItem(Base):
    __tablename__ = "news_items"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)

    original_url = Column(String, unique=True, nullable=False)

    # Original content
    title_original = Column(String, nullable=True)
    text_original = Column(Text, nullable=True)

    # Russian rewrite
    title_ru = Column(String, nullable=True)
    summary_ru = Column(Text, nullable=True)
    quote_ru = Column(Text, nullable=True)
    why_important_ru = Column(Text, nullable=True)
    market_impact_ru = Column(Text, nullable=True)

    original_language = Column(String, nullable=True)

    # Media
    image_url = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    media_type = Column(String, nullable=True)  # "image" | "video" | None

    # Classification
    category = Column(String, nullable=True)         # "world" | "economy" | "discard"
    routing_confidence = Column(Float, default=0.0)  # 0.0 – 1.0
    routing_reason = Column(Text, nullable=True)     # human-readable reason

    # Quality & trust
    importance_score = Column(Integer, default=0, nullable=False)
    quality_score = Column(Integer, default=0, nullable=False)
    trust_score = Column(Float, default=0.7)         # inherited from source, adjusted per item

    # Deduplication
    is_duplicate = Column(Boolean, default=False, nullable=False)
    cluster_id = Column(String, nullable=True)       # story cluster identifier
    is_primary_in_cluster = Column(Boolean, default=True)

    # Moderation
    moderation_decision = Column(String, nullable=True)  # "auto_publish" | "send_to_moderation" | "discard"
    moderation_reason = Column(Text, nullable=True)
    moderation_flags = Column(Text, nullable=True)  # JSON list of flag strings

    is_relevant = Column(Boolean, default=True, nullable=False)

    # Rewrite tracking
    rewrite_status = Column(String, default="pending", nullable=False)
    rewrite_model = Column(String, nullable=True)

    # Lifecycle
    status = Column(String, default="new", nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
