from sqlalchemy import Boolean, Column, Float, Integer, String, Text

from app.db.session import Base


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)

    # Identity
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)          # RSS feed URL
    site_url = Column(String, nullable=True)      # Homepage URL
    source_type = Column(String, nullable=False)  # rss | atom | api | scrape

    # Classification metadata
    category_hint = Column(String, nullable=True)   # world | economy | ...
    country_hint = Column(String, nullable=True)    # ru | us | uk | global | ...
    language_hint = Column(String, nullable=True)   # ru | en | de | ...
    topic_tags = Column(Text, nullable=True)        # JSON list: ["banks", "macro"]
    clusters = Column(Text, nullable=True)          # JSON list: ["world", "geo"]

    # Routing
    route_default = Column(String, nullable=True)   # "world" | "economy"

    # Quality signals
    trust_score = Column(Float, default=0.7)
    priority_weight = Column(Float, default=1.0)
    freshness_score = Column(Float, default=0.7)   # how often it publishes fresh news
    media_score = Column(Float, default=0.5)       # how often it has good images

    # Capabilities
    supports_images = Column(Boolean, default=True)
    supports_video = Column(Boolean, default=False)
    paywall_risk = Column(Boolean, default=False)

    # Operational
    is_active = Column(Boolean, default=True, nullable=False)
    poll_interval_minutes = Column(Integer, default=10, nullable=False)

    # Health tracking
    last_checked_at = Column(String, nullable=True)   # ISO timestamp
    last_success_at = Column(String, nullable=True)   # ISO timestamp
    consecutive_failures = Column(Integer, default=0)
    health_status = Column(String, default="unknown")  # ok | slow | dead | empty
    avg_response_ms = Column(Integer, nullable=True)
    last_item_count = Column(Integer, nullable=True)

    # Notes
    notes = Column(Text, nullable=True)
