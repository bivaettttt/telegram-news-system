from __future__ import annotations

import html
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup


DEFAULT_TIMEOUT = 20.0

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def clean_html_text(value: str | None) -> str:
    if not value:
        return ""

    text = html.unescape(str(value))

    if "<" in text and ">" in text:
        try:
            text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        except Exception:
            pass

    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"www\.\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def download_article_html(url: str) -> str:
    with httpx.Client(
        headers=DEFAULT_HEADERS,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _pick_main_content_block(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    selectors = [
        "article",
        "main",
        ".article",
        ".article__text",
        ".article__content",
        ".article-body",
        ".article__body",
        ".entry-content",
        ".post-content",
        ".post__content",
        ".content",
        ".news__text",
        ".js-mediator-article",
        '[itemprop="articleBody"]',
    ]

    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return node

    body = soup.body
    if body:
        return body

    return None


def _extract_best_text_block(soup: BeautifulSoup) -> str:
    container = _pick_main_content_block(soup)
    if not container:
        return ""

    for tag in container.select("script, style, noscript, svg, iframe, form, header, footer"):
        tag.decompose()

    paragraphs = []
    for node in container.select("p, li, h2, h3"):
        text = clean_html_text(node.get_text(" ", strip=True))
        if len(text) >= 40:
            paragraphs.append(text)

    if paragraphs:
        return "\n".join(paragraphs[:12]).strip()

    fallback = clean_html_text(container.get_text(" ", strip=True))
    return fallback


def extract_lead_image_url(html_text: str) -> str | None:
    soup = BeautifulSoup(html_text, "html.parser")

    meta_candidates = [
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('meta[property="og:image:url"]', "content"),
        ('meta[name="og:image"]', "content"),
    ]

    for selector, attr in meta_candidates:
        tag = soup.select_one(selector)
        if tag and tag.get(attr):
            return tag.get(attr)

    img = soup.select_one("article img, main img, .article img, .entry-content img, img")
    if img and img.get("src"):
        return img.get("src")

    return None


def extract_lead_video_url(html_text: str) -> str | None:
    soup = BeautifulSoup(html_text, "html.parser")

    meta_candidates = [
        ('meta[property="og:video"]', "content"),
        ('meta[property="og:video:url"]', "content"),
        ('meta[name="twitter:player:stream"]', "content"),
    ]

    for selector, attr in meta_candidates:
        tag = soup.select_one(selector)
        if tag and tag.get(attr):
            return tag.get(attr)

    video = soup.select_one("video source, video")
    if video:
        src = video.get("src")
        if src:
            return src

    return None


def extract_title_from_html(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    meta_candidates = [
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
    ]

    for selector, attr in meta_candidates:
        tag = soup.select_one(selector)
        if tag and tag.get(attr):
            return clean_html_text(tag.get(attr))

    if soup.title and soup.title.text:
        return clean_html_text(soup.title.text)

    h1 = soup.select_one("h1")
    if h1:
        return clean_html_text(h1.get_text(" ", strip=True))

    return ""


def extract_summary_from_html(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    meta_candidates = [
        ('meta[name="description"]', "content"),
        ('meta[property="og:description"]', "content"),
        ('meta[name="twitter:description"]', "content"),
    ]

    for selector, attr in meta_candidates:
        tag = soup.select_one(selector)
        if tag and tag.get(attr):
            text = clean_html_text(tag.get(attr))
            if len(text) >= 80:
                return text

    article_text = _extract_best_text_block(soup)
    if not article_text:
        return ""

    if len(article_text) > 2500:
        article_text = article_text[:2500].rsplit(" ", 1)[0].strip()

    return article_text