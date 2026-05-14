"""
Deduplication — multi-level: exact URL → title fuzzy → story cluster.

Levels:
  1. Exact URL (canonicalized)
  2. Near-duplicate by title (RapidFuzz ratio + Jaccard)
  3. Story cluster: same event, different angles (token overlap)

For near/semantic duplicates, we keep the item with the highest
combined trust_score + completeness.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rapidfuzz import fuzz

# Tokens that add no discriminative value
_NOISE_TOKENS = {
    "срочно", "breaking", "live", "обновлено", "urgent", "exclusive",
    "молния", "flash", "alert", "update", "latest", "just", "now",
}

# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    text = title.lower().strip().replace("ё", "е")
    text = re.sub(r'["\'«»„""]', "", text)
    text = re.sub(r"[^a-zа-я0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_tokens(title: str | None) -> set[str]:
    normalized = normalize_title(title)
    return {
        tok for tok in normalized.split()
        if len(tok) >= 4 and tok not in _NOISE_TOKENS
    }


def canonicalize_url(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    filtered_qs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
    ]
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/"),
        urlencode(filtered_qs),
        "",
    ))


# ---------------------------------------------------------------------------
# Similarity checks
# ---------------------------------------------------------------------------

def are_titles_similar(
    title_a: str | None,
    title_b: str | None,
    threshold: int = 88,
) -> bool:
    norm_a = normalize_title(title_a)
    norm_b = normalize_title(title_b)
    if not norm_a or not norm_b:
        return False

    ratio = fuzz.ratio(norm_a, norm_b)
    partial = fuzz.partial_ratio(norm_a, norm_b)
    tokens_a = title_tokens(title_a)
    tokens_b = title_tokens(title_b)
    jaccard = (
        len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        if tokens_a and tokens_b else 0.0
    )

    return ratio >= threshold or partial >= 94 or jaccard >= 0.72


def are_same_story(
    title_a: str | None,
    summary_a: str | None,
    title_b: str | None,
    summary_b: str | None,
    threshold: int = 82,
) -> bool:
    """
    Looser check for story clustering — same event but possibly different angles.
    Uses both title AND summary tokens.
    """
    if are_titles_similar(title_a, title_b, threshold=threshold):
        return True

    # Token overlap on combined title+summary
    def _tokens(t: str | None, s: str | None) -> set[str]:
        blob = f"{normalize_title(t)} {normalize_title(s)}"
        return {tok for tok in blob.split() if len(tok) >= 5 and tok not in _NOISE_TOKENS}

    tokens_a = _tokens(title_a, summary_a)
    tokens_b = _tokens(title_b, summary_b)

    if not tokens_a or not tokens_b:
        return False

    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    return jaccard >= 0.60


# ---------------------------------------------------------------------------
# Source quality comparison (pick the "better" item to keep as primary)
# ---------------------------------------------------------------------------

def pick_primary_source(
    item_a: dict,  # {trust_score, text_length, has_image}
    item_b: dict,
) -> str:
    """Return 'a' or 'b' — whichever is the better primary source."""
    score_a = _source_quality_score(item_a)
    score_b = _source_quality_score(item_b)
    return "a" if score_a >= score_b else "b"


def _source_quality_score(item: dict) -> float:
    trust = float(item.get("trust_score") or 0.5)
    text_len = int(item.get("text_length") or 0)
    has_image = bool(item.get("has_image"))
    has_video = bool(item.get("has_video"))

    score = trust * 10
    if text_len > 400:
        score += 2
    elif text_len > 200:
        score += 1
    if has_image:
        score += 1.5
    if has_video:
        score += 1.0
    return score
