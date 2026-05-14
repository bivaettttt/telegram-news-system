from __future__ import annotations
import json
import yaml
import httpx
from sqlalchemy.orm import Session
from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.source import Source

logger = setup_logger("seed_sources")
SOURCES_YAML = "app/config/sources.yaml"

def is_rss_accessible(url: str, timeout: int = 5) -> bool:
    """Check if RSS URL returns HTTP 200."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            return response.status_code == 200
    except Exception as e:
        logger.warning("Failed to access RSS URL %s: %s", url, str(e))
        return False

def seed(db: Session) -> None:
    with open(SOURCES_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    sources = data.get("sources", [])
    added = 0
    updated = 0

    seen_urls = set()

    for s in sources:
        url = s.get("url")
        if not url:
            continue

        # Skip duplicates in YAML
        if url in seen_urls:
            logger.warning("Duplicate URL in YAML skipped: %s", url)
            continue
        seen_urls.add(url)

        # Skip inaccessible RSS
        if not is_rss_accessible(url):
            logger.warning("RSS not accessible, skipping: %s", url)
            continue

        existing = db.query(Source).filter(Source.url == url).first()

        if existing:
            # Update metadata, keep operational fields
            existing.name = s.get("name", existing.name)
            existing.site_url = s.get("site_url")
            existing.source_type = s.get("type", "rss")
            existing.category_hint = s.get("category", existing.category_hint)
            existing.country_hint = s.get("country", existing.country_hint)
            existing.language_hint = s.get("language", existing.language_hint)
            existing.topic_tags = json.dumps(s.get("topic_tags", []))
            existing.clusters = json.dumps(s.get("clusters", []))
            existing.route_default = s.get("route_default", existing.route_default)
            existing.trust_score = s.get("trust_score", existing.trust_score)
            existing.priority_weight = s.get("priority_weight", existing.priority_weight)
            existing.freshness_score = s.get("freshness_score", existing.freshness_score)
            existing.media_score = s.get("media_score", existing.media_score)
            existing.supports_images = s.get("supports_images", existing.supports_images)
            existing.supports_video = s.get("supports_video", existing.supports_video)
            existing.paywall_risk = s.get("paywall_risk", existing.paywall_risk)
            existing.is_active = s.get("enabled", existing.is_active)
            existing.poll_interval_minutes = s.get("poll_interval_minutes", existing.poll_interval_minutes)
            existing.notes = s.get("notes")
            updated += 1
        else:
            source = Source(
                name=s.get("name", ""),
                url=url,
                site_url=s.get("site_url"),
                source_type=s.get("type", "rss"),
                category_hint=s.get("category"),
                country_hint=s.get("country"),
                language_hint=s.get("language"),
                topic_tags=json.dumps(s.get("topic_tags", [])),
                clusters=json.dumps(s.get("clusters", [])),
                route_default=s.get("route_default"),
                trust_score=s.get("trust_score", 0.7),
                priority_weight=s.get("priority_weight", 1.0),
                freshness_score=s.get("freshness_score", 0.7),
                media_score=s.get("media_score", 0.5),
                supports_images=s.get("supports_images", True),
                supports_video=s.get("supports_video", False),
                paywall_risk=s.get("paywall_risk", False),
                is_active=s.get("enabled", True),
                poll_interval_minutes=s.get("poll_interval_minutes", 10),
                notes=s.get("notes"),
            )
            db.add(source)
            added += 1

    db.commit()
    logger.info("seed_sources: %d added, %d updated", added, updated)
    print(f"Sources seeded: +{added} new, {updated} updated")

def main() -> None:
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()

if __name__ == "__main__":
    main()