import re
from html import unescape

from bs4 import BeautifulSoup


def clean_html_text(raw_text: str | None) -> str:
    if not raw_text:
        return ""

    text = unescape(raw_text)
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ")

    text = re.sub(r"\s+", " ", text).strip()
    return text