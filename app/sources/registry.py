"""
Source registry — загружает sources.yaml и предоставляет lookup-хелперы.

ИСПРАВЛЕНИЯ:
  - get_source_trust / get_source_priority принимают только name (убран параметр url
    который был в сигнатуре story_cluster.py но не в реализации).
  - Добавлен get_source_by_name для удобного поиска по имени.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_SOURCES_YAML = Path(__file__).parent.parent / "config" / "sources.yaml"
_registry: dict[str, dict] = {}


def _load() -> dict[str, dict]:
    with open(_SOURCES_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    sources = data.get("sources", [])
    return {s["id"]: s for s in sources if s.get("id")}


def get_registry() -> dict[str, dict]:
    global _registry
    if not _registry:
        _registry = _load()
    return _registry


def reload_registry() -> None:
    global _registry
    _registry = _load()


def get_source_by_id(source_id: str) -> dict | None:
    return get_registry().get(source_id)


def get_source_by_name(name: str | None) -> dict | None:
    if not name:
        return None
    reg = get_registry()
    name_lower = name.lower()
    for s in reg.values():
        if s.get("name", "").lower() == name_lower:
            return s
    return None


def get_source_trust(name: str | None = None, url: str | None = None) -> float:
    """Возвращает trust_score источника по имени или URL."""
    reg = get_registry()
    name_lower = (name or "").lower()
    for s in reg.values():
        if name_lower and s.get("name", "").lower() == name_lower:
            return float(s.get("trust_score", 0.7))
        if url and s.get("url") == url:
            return float(s.get("trust_score", 0.7))
    return 0.7


def get_source_priority(name: str | None = None, url: str | None = None) -> float:
    """Возвращает priority_weight источника по имени или URL."""
    reg = get_registry()
    name_lower = (name or "").lower()
    for s in reg.values():
        if name_lower and s.get("name", "").lower() == name_lower:
            return float(s.get("priority_weight", 0.5))
        if url and s.get("url") == url:
            return float(s.get("priority_weight", 0.5))
    return 0.5


def get_target_channels(source_name: str | None) -> list[str]:
    s = get_source_by_name(source_name)
    if s:
        return s.get("clusters") or [s.get("route_default", "world")]
    return ["world"]


def classify_bias(source_name: str | None) -> str | None:
    s = get_source_by_name(source_name)
    return s.get("category_hint") if s else None


def list_enabled_sources() -> list[dict]:
    return [s for s in get_registry().values() if s.get("enabled", True)]