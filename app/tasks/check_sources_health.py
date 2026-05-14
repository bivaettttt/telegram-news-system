"""
Source health checker — probes all RSS feeds and auto-disables dead ones.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import NamedTuple

import feedparser
import httpx

from app.core.logger import setup_logger
from app.db.session import SessionLocal
from app.models.source import Source

logger = setup_logger("health_check")

TIMEOUT_SECONDS = 20
SLOW_THRESHOLD_MS = 8000
MAX_CONCURRENT = 8
DEAD_FAILURES_THRESHOLD = 5


class FeedProbeResult(NamedTuple):
    source_id: int
    source_name: str
    url: str
    http_status: int | None
    response_ms: int | None
    entry_count: int
    fresh_entry_count: int
    error: str | None

    @property
    def is_dead(self) -> bool:
        return self.http_status != 200 or self.entry_count == 0

    @property
    def is_slow(self) -> bool:
        return self.response_ms is not None and self.response_ms > SLOW_THRESHOLD_MS

    @property
    def is_empty(self) -> bool:
        return self.entry_count == 0 and self.http_status == 200

    @property
    def health_status(self) -> str:
        if self.error and "timeout" in (self.error or "").lower():
            return "dead"
        if self.is_dead:
            return "dead"
        if self.is_empty:
            return "empty"
        if self.is_slow:
            return "slow"
        return "ok"


async def probe_feed(client: httpx.AsyncClient, source_id: int, source_name: str, url: str) -> FeedProbeResult:
    t0 = time.monotonic()
    try:
        resp = await client.get(url, timeout=TIMEOUT_SECONDS, follow_redirects=True)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        http_status = resp.status_code

        if http_status != 200:
            return FeedProbeResult(source_id, source_name, url, http_status, elapsed_ms, 0, 0, f"HTTP {http_status}")

        feed = feedparser.parse(resp.text)
        entries = feed.get("entries", [])
        now = datetime.now(tz=timezone.utc)
        fresh_count = 0

        for entry in entries:
            published = entry.get("published_parsed")
            if not published:
                continue
            try:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                age_h = (now - pub_dt).total_seconds() / 3600
                if age_h <= 24:
                    fresh_count += 1
            except Exception:
                pass

        return FeedProbeResult(source_id, source_name, url, http_status, elapsed_ms, len(entries), fresh_count, None)

    except httpx.TimeoutException:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return FeedProbeResult(source_id, source_name, url, None, elapsed_ms, 0, 0, "timeout")
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return FeedProbeResult(source_id, source_name, url, None, elapsed_ms, 0, 0, str(exc)[:120])


async def run_health_check() -> list[FeedProbeResult]:
    db = SessionLocal()
    try:
        sources = db.query(Source).filter(Source.is_active == True).all()
        logger.info("Health check: probing %d active sources", len(sources))

        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def _guarded(client, s):
            async with sem:
                return await probe_feed(client, s.id, s.name, s.url)

        headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/2.0)"}
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=TIMEOUT_SECONDS) as client:
            results: list[FeedProbeResult] = await asyncio.gather(*[_guarded(client, s) for s in sources])

        now_iso = datetime.now(tz=timezone.utc).isoformat()

        for result in results:
            source = db.query(Source).filter(Source.id == result.source_id).first()
            if not source:
                continue

            source.last_checked_at = now_iso
            source.avg_response_ms = result.response_ms
            source.last_item_count = result.entry_count
            source.health_status = result.health_status

            if result.health_status == "ok":
                source.consecutive_failures = 0
                source.last_success_at = now_iso
            else:
                source.consecutive_failures = (source.consecutive_failures or 0) + 1
                if source.consecutive_failures >= DEAD_FAILURES_THRESHOLD:
                    source.is_active = False
                    logger.warning("Auto-disabled dead source: %s (%d failures)", source.name, source.consecutive_failures)

        db.commit()

        ok = sum(1 for r in results if r.health_status == "ok")
        slow = sum(1 for r in results if r.health_status == "slow")
        dead = sum(1 for r in results if r.health_status == "dead")
        empty = sum(1 for r in results if r.health_status == "empty")

        logger.info("Health check done — OK: %d | slow: %d | dead: %d | empty: %d", ok, slow, dead, empty)
        return results

    finally:
        db.close()


def main() -> None:
    results = asyncio.run(run_health_check())
    print(f"\n{'Source':<35} {'Status':<8} {'HTTP':<6} {'ms':<7} {'Entries':<9} {'Fresh'}")
    print("-" * 80)
    for r in sorted(results, key=lambda x: x.health_status):
        print(f"{r.source_name[:34]:<35} {r.health_status:<8} {str(r.http_status or '?'):<6} {str(r.response_ms or '?'):<7} {r.entry_count:<9} {r.fresh_entry_count}")


if __name__ == "__main__":
    main()