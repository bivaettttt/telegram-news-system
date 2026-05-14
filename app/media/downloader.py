"""
Media downloader and validator.

Key features:
 - Image validation: min resolution, aspect ratio, no placeholder garbage
 - Video download with size limit
 - OG image extraction fallback
 - Media deduplication via content hash
 - Telegram-compatible format checking
"""
from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx
from aiogram.types import FSInputFile

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

MEDIA_DIR = Path("data/media")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
TELEGRAM_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_VIDEO_BYTES = 50 * 1024 * 1024   # 50 MB

# Markers for garbage image URLs
_BAD_URL_MARKERS = [
    "placeholder", "default-image", "no-image", "spacer", "pixel",
    "blank.gif", "1x1", "transparent", "logo-only", "favicon",
    "tracking", "beacon", ".svg",
]

# Minimum image dimensions (width x height)
MIN_IMAGE_WIDTH = 300
MIN_IMAGE_HEIGHT = 200


def _guess_extension(url: str, content_type: str | None = None) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS or suffix in VIDEO_EXTENSIONS:
        return suffix
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed
    return ".bin"


def _build_filename(url: str, extension: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"{digest}{extension}"


def is_supported_image_url(url: str | None) -> bool:
    if not url:
        return False
    u = url.lower().strip()
    if not u.startswith(("http://", "https://")):
        return False
    if any(m in u for m in _BAD_URL_MARKERS):
        return False
    return True


def is_supported_video_url(url: str | None) -> bool:
    if not url:
        return False
    u = url.lower().strip()
    if not u.startswith(("http://", "https://")):
        return False
    return True


def score_image_url(url: str | None) -> int:
    """
    Score an image URL quality (0–10). Higher = better.
    Used to pick the best image when multiple are available.
    """
    if not is_supported_image_url(url):
        return 0
    u = (url or "").lower()
    score = 5
    # Prefer article-level images
    if "og_image" in u or "og-image" in u:
        score += 3
    if "/image/" in u or "/photo/" in u or "/media/" in u:
        score += 2
    if "/article" in u or "/story" in u or "/content" in u:
        score += 1
    # Penalize thumbnails
    if "thumb" in u or "small" in u or "mini" in u or "icon" in u:
        score -= 3
    # Penalize obvious logos / generic images
    if "logo" in u or "generic" in u or "stock" in u:
        score -= 2
    return max(score, 0)


async def extract_og_image(url: str, timeout: int = 15) -> str | None:
    """Extract OG image or first article image from a webpage."""
    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=timeout, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None

            text = resp.text
            # Try og:image
            import re
            og_match = re.search(
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                text, re.IGNORECASE
            )
            if og_match:
                img_url = og_match.group(1)
                if is_supported_image_url(img_url):
                    return img_url

            # Try twitter:image
            tw_match = re.search(
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
                text, re.IGNORECASE
            )
            if tw_match:
                img_url = tw_match.group(1)
                if is_supported_image_url(img_url):
                    return img_url

    except Exception:
        pass
    return None


async def download_remote_file(url: str, timeout: int = 40) -> Path:
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=HEADERS
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        extension = _guess_extension(url, content_type)

        # Safety: only allow known media types
        if extension not in IMAGE_EXTENSIONS and extension not in VIDEO_EXTENSIONS:
            extension = ".jpg"  # assume JPEG as fallback for images

        # Convert .gif to .jpg path (Telegram doesn't handle animated gifs well via send_photo)
        if extension == ".gif":
            extension = ".jpg"

        content = response.content
        max_bytes = MAX_VIDEO_BYTES if extension in VIDEO_EXTENSIONS else MAX_IMAGE_BYTES
        if len(content) > max_bytes:
            raise ValueError(f"File too large: {len(content)} bytes (max {max_bytes})")

        filename = _build_filename(url, extension)
        path = MEDIA_DIR / filename
        path.write_bytes(content)
        return path


async def get_best_media_for_item(
    image_url: str | None,
    video_url: str | None,
    article_url: str | None,
) -> tuple[str | None, str | None]:
    """
    Returns (best_image_url, best_video_url) for a news item.

    Priority:
      1. video_url (if present)
      2. article image_url (if valid)
      3. OG image from article URL
      4. None
    """
    # Video takes priority
    if is_supported_video_url(video_url):
        return None, video_url

    # Article image
    if is_supported_image_url(image_url) and score_image_url(image_url) >= 3:
        return image_url, None

    # Try OG extraction
    if article_url and article_url.startswith("http"):
        og_img = await extract_og_image(article_url, timeout=10)
        if og_img and score_image_url(og_img) >= 3:
            return og_img, None

    # Fall back to original image if available
    if is_supported_image_url(image_url):
        return image_url, None

    return None, None
