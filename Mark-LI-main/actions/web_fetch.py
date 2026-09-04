"""Fetch a web page and turn it into readable text (optionally distilled).

Used by ADHITHIYA for deep research: read the actual page behind a search hit
instead of guessing from a snippet.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from memory.config_manager import load_api_keys

_MAX_RAW = 6000
_MAX_SUMMARY = 1200


class _TextExtractor(HTMLParser):
    """Strip tags and drop script/style/nav content to plain text."""

    _SKIP = {"script", "style", "noscript", "svg", "head", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        raw = " ".join(self._chunks)
        raw = re.sub(r"\s+", " ", raw)
        return raw.strip()


def _api_key() -> str:
    try:
        return str(load_api_keys().get("gemini_api_key", "") or "")
    except Exception:
        return ""


def _fetch(url: str) -> str:
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if "html" in content_type or "text" in content_type:
        parser = _TextExtractor()
        parser.feed(resp.text)
        return parser.text()
    return resp.text


def _distill(text: str, url: str, api_key: str) -> str:
    from google import genai
    client = genai.Client(api_key=api_key)
    prompt = (
        f"Summarise the main points of this web page ({url}) in 4-6 short bullet "
        f"points plus a one-line takeaway. Keep all facts accurate to the text; "
        f"do not invent. Text:\n\n{text[:_MAX_RAW]}"
    )
    resp = client.models.generate_content(model="gemini-flash-latest", contents=prompt)
    return (resp.text or "").strip()


def web_fetch(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    url = str(params.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return "Provide a full http(s) URL to fetch."
    if player:
        player.write_log(f"[Fetch] {url[:100]}")
    try:
        text = _fetch(url)
    except Exception as e:  # noqa: BLE001
        return f"Could not fetch {url}: {e}"

    text = (text or "").strip()
    if not text:
        return "The page returned no readable text."

    api_key = _api_key()
    if api_key and len(text) > 400:
        try:
            summary = _distill(text, url, api_key)
            if summary:
                return summary[:_MAX_SUMMARY]
        except Exception as e:  # noqa: BLE001
            print(f"[Fetch] distill failed: {e}")
    return text[:_MAX_RAW]
