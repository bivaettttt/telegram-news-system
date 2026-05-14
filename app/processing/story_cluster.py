from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from app.models.news_item import NewsItem
from app.models.source import Source
from app.sources.registry import get_source_priority, get_source_trust

STOPWORDS = {
    'и','в','во','на','по','с','со','к','ко','за','от','до','из','у','о','об','для','при','под','над','не','что','как','это',
    'the','a','an','to','of','in','on','for','and','with','at','from','by','is','are','will','after','amid','over',
    'его','ее','их','about','into','than','that','this'
}

TOPIC_KEYWORDS = {
    'rates': ['ставк', 'rate', 'фрс', 'fed', 'ecb', 'цб', 'центробанк', 'банк россии', 'monetary'],
    'inflation': ['инфляц', 'cpi', 'цен', 'prices'],
    'fx': ['рубл', 'доллар', 'евро', 'юан', 'fx', 'currency', 'валют'],
    'oil_gas': ['нефть', 'oil', 'газ', 'gas', 'спг', 'lng', 'opec'],
    'banks': ['банк', 'bank', 'кредит', 'ипотек', 'депозит'],
    'markets': ['акци', 'stocks', 'бирж', 'рынок', 'облигац', 'bonds', 'индекс'],
    'war': ['война', 'war', 'удар', 'strike', 'атака', 'attack', 'дрон', 'drone', 'ракет'],
    'diplomacy': ['переговор', 'sanctions', 'санкци', 'президент', 'minister', 'министр', 'nato', 'ес'],
}

ENTITY_RE = re.compile(r"(?:[A-Z][a-z]{2,}|[А-ЯЁ][а-яё]{2,}|[A-Z]{2,}|[А-ЯЁ]{2,})")


def clean_text(*parts: str | None) -> str:
    text = ' '.join(part or '' for part in parts).strip().replace('ё', 'е').lower()
    text = re.sub(r'[^a-zа-я0-9\s-]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def tokenize(text: str) -> set[str]:
    return {t for t in clean_text(text).split() if len(t) >= 4 and t not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


def story_signature(item: NewsItem) -> set[str]:
    base = tokenize(f"{item.title_ru or item.title_original or ''} {item.summary_ru or item.text_original or ''}")
    return {t for t in base if len(t) >= 5}


def extract_topics(text: str) -> list[str]:
    topics = []
    lowered = clean_text(text)
    for topic, keys in TOPIC_KEYWORDS.items():
        if any(k in lowered for k in keys):
            topics.append(topic)
    return topics


def extract_entities(*parts: str | None) -> list[str]:
    text = ' '.join(part or '' for part in parts)
    entities = []
    seen = set()
    for m in ENTITY_RE.findall(text):
        val = m.strip()
        norm = val.lower()
        if len(val) < 3 or norm in seen:
            continue
        seen.add(norm)
        entities.append(val)
        if len(entities) >= 6:
            break
    return entities


def sentence_split(text: str) -> list[str]:
    raw = re.split(r'(?<=[.!?])\s+', ' '.join((text or '').split()))
    return [x.strip(' •-—	') for x in raw if len(x.strip(' •-—	')) >= 35]


def article_rank(item: NewsItem, source: Source | None) -> float:
    quality = float(item.quality_score or 0)
    importance = float(item.importance_score or 0)
    priority = get_source_priority(name=source.name if source else None, url=source.url if source else None)
    trust = get_source_trust(name=source.name if source else None, url=source.url if source else None)
    media_bonus = 0.5 if (item.video_url or item.image_url) else 0.0
    freshness_bonus = 0.0
    if item.published_at:
        published_at = item.published_at if item.published_at.tzinfo else item.published_at.replace(tzinfo=timezone.utc)
        freshness_hours = max(0.0, (datetime.now(timezone.utc) - published_at).total_seconds() / 3600)
        freshness_bonus = max(0.0, 72.0 - freshness_hours) / 24.0
    return quality + importance + priority * 3.0 + trust * 2.0 + freshness_bonus + media_bonus


@dataclass
class StoryCluster:
    category: str
    items: list[NewsItem] = field(default_factory=list)
    signatures: list[set[str]] = field(default_factory=list)

    def add(self, item: NewsItem) -> None:
        self.items.append(item)
        self.signatures.append(story_signature(item))

    @property
    def size(self) -> int:
        return len(self.items)

    def similarity(self, item: NewsItem) -> float:
        sig = story_signature(item)
        if not sig:
            return 0.0
        return max((jaccard(sig, existing) for existing in self.signatures), default=0.0)


def cluster_news_items(items: Iterable[NewsItem], source_map: dict[int, Source], threshold: float = 0.42) -> list[StoryCluster]:
    clusters: list[StoryCluster] = []
    sorted_items = sorted(items, key=lambda x: article_rank(x, source_map.get(x.source_id)), reverse=True)
    for item in sorted_items:
        matched = None
        best = 0.0
        for cluster in clusters:
            if (cluster.category or '') != (item.category or ''):
                continue
            score = cluster.similarity(item)
            if score > best:
                best = score
                matched = cluster
        if matched and best >= threshold:
            matched.add(item)
        else:
            cluster = StoryCluster(category=item.category or 'world')
            cluster.add(item)
            clusters.append(cluster)
    return clusters


def pick_primary_item(cluster: StoryCluster, source_map: dict[int, Source]) -> NewsItem:
    return max(cluster.items, key=lambda x: article_rank(x, source_map.get(x.source_id)))


def pick_best_media_item(cluster: StoryCluster, source_map: dict[int, Source]) -> NewsItem:
    media_items = [x for x in cluster.items if x.video_url or x.image_url]
    if media_items:
        return max(media_items, key=lambda x: article_rank(x, source_map.get(x.source_id)))
    return pick_primary_item(cluster, source_map)


def collect_cluster_bullets(cluster: StoryCluster) -> list[str]:
    ranked = sorted(cluster.items, key=lambda x: (len(x.summary_ru or x.text_original or ''), x.quality_score or 0), reverse=True)
    bullets = []
    seen = set()
    for item in ranked:
        for sentence in sentence_split(item.summary_ru or item.text_original or ''):
            norm = clean_text(sentence)
            if len(norm) < 45 or norm in seen:
                continue
            seen.add(norm)
            bullets.append(sentence)
            if len(bullets) >= 5:
                return bullets
    return bullets


def build_cluster_summary(cluster: StoryCluster, max_bullets: int = 3) -> str:
    bullets = collect_cluster_bullets(cluster)[:max_bullets]
    return ' '.join(bullets).strip()


def cluster_source_names(cluster: StoryCluster, source_map: dict[int, Source], max_names: int = 4) -> list[str]:
    names = []
    seen = set()
    for item in sorted(cluster.items, key=lambda x: article_rank(x, source_map.get(x.source_id)), reverse=True):
        source = source_map.get(item.source_id)
        if not source or source.name in seen:
            continue
        seen.add(source.name)
        names.append(source.name)
        if len(names) >= max_names:
            break
    return names


def cluster_strength(cluster: StoryCluster, source_map: dict[int, Source]) -> float:
    diversity = len(cluster_source_names(cluster, source_map, max_names=10))
    max_rank = max(article_rank(item, source_map.get(item.source_id)) for item in cluster.items)
    return max_rank + diversity * 1.1 + max(0, cluster.size - 1) * 0.6
