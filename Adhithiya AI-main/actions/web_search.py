"""Live web search backed by DuckDuckGo's ``ddgs`` package.

This module deliberately does not substitute model memory for search results:
all returned claims are titles/snippets from fetched pages, with their source
URLs. When the search backend is unavailable or returns nothing, that is stated
plainly. ``search_results`` is also the narrow, approved search API available to
self-learning and generated plugins.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


class WebSearchUnavailable(RuntimeError):
    """Raised when the live web-search backend cannot retrieve results."""


def _get_ddgs():
    """Load the supported live-search client; never silently use a retired one."""
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError as exc:
        raise WebSearchUnavailable(
            "Live web search is unavailable because the 'ddgs' package is missing. "
            "Install ddgs and rebuild the application."
        ) from exc


def _clean_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clean_url(value: object) -> str:
    """Accept only ordinary HTTP(S) page URLs and remove credentials/fragments."""
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.casefold()
        host = parsed.hostname
        if (scheme not in {"http", "https"} or not host
                or parsed.username is not None or parsed.password is not None):
            return ""
        port = parsed.port  # raises ValueError for malformed ports
        host = host.casefold()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{port}" if port is not None else host
        return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))
    except (TypeError, ValueError):
        return ""


def _text_result(row: object) -> dict | None:
    if not isinstance(row, dict):
        return None
    title = _clean_text(row.get("title"), 240)
    snippet = _clean_text(row.get("body") or row.get("snippet"), 800)
    url = _clean_url(row.get("href") or row.get("url"))
    if not url or not (title or snippet):
        return None
    return {"title": title, "snippet": snippet, "url": url}


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    """Retrieve real text-search results. Backend errors are not disguised as 0 hits."""
    query = str(query or "").strip()
    if not query:
        return []

    DDGS = _get_ddgs()
    results: list[dict] = []
    try:
        with DDGS() as ddgs:
            rows = ddgs.text(query, max_results=max_results)
            for row in rows or ():
                record = _text_result(row)
                if record:
                    results.append(record)
    except Exception as exc:
        if results:
            print(f"[WebSearch] Text search returned partial results before failing: {exc}")
        else:
            raise WebSearchUnavailable(f"Live web text search failed: {exc}") from exc
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """Retrieve actual article results from the live news-search endpoint."""
    query = str(query or "").strip()
    if not query:
        return []

    DDGS = _get_ddgs()
    results: list[dict] = []
    try:
        with DDGS() as ddgs:
            rows = ddgs.news(query, max_results=max_results)
            for row in rows or ():
                if not isinstance(row, dict):
                    continue
                title = _clean_text(row.get("title"), 240)
                snippet = _clean_text(row.get("body") or row.get("snippet"), 500)
                url = _clean_url(row.get("url") or row.get("href"))
                if not url or not title:
                    continue
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": url,
                    "source": _clean_text(row.get("source"), 100),
                })
    except Exception as exc:
        if results:
            print(f"[WebSearch] News search returned partial results before failing: {exc}")
        else:
            raise WebSearchUnavailable(f"Live web news search failed: {exc}") from exc
    return results


def search_results(query: str, max_results: int = 6) -> list[dict]:
    """Return bounded, source-linked live search results for approved callers.

    Each result has ``title``, ``snippet``, and ``url`` fields. Raises
    :class:`WebSearchUnavailable` on a backend failure; an empty list means a
    search completed but no usable source-linked results were returned.
    """
    query = str(query or "").strip()[:500]
    if not query:
        return []
    try:
        limit = max(1, min(int(max_results), 10))
    except (TypeError, ValueError):
        limit = 6
    return _ddg_search(query, max_results=limit)


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"Live web search returned no source-linked results for: {query}"

    lines = [f"Live web search results for: {query}", ""]
    for i, result in enumerate(results, 1):
        if result.get("title"):
            lines.append(f"{i}. {result['title']}")
        if result.get("snippet"):
            lines.append(f"   {result['snippet']}")
        if result.get("url"):
            lines.append(f"   Source: {result['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"Live news search returned no source-linked articles for: {query}"

    lines = [f"Live news search results for: {query}", ""]
    for i, result in enumerate(results, 1):
        source = f" [{result['source']}]" if result.get("source") else ""
        lines.append(f"{i}. {result['title']}{source}")
        if result.get("snippet"):
            lines.append(f"   {result['snippet'][:240]}")
        lines.append(f"   Source: {result['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _search(query: str) -> str:
    """Default search: show fetched results, never invent an answer from model memory."""
    return _format_ddg(query, search_results(query, max_results=6))


def _news(query: str) -> str:
    """Show fetched news articles; never fabricate current headlines as fallback."""
    news_query = str(query or "").strip() or "world news today"
    return _format_news(news_query, _ddg_news(news_query, max_results=8))


def _research(query: str) -> str:
    """Return a wider set of live, source-linked results for research queries."""
    return _format_ddg(query, search_results(query, max_results=10))


def _price(query: str) -> str:
    """Look up current prices using live source-linked search results."""
    price_query = f"current price of {str(query or '').strip()}"
    return _format_ddg(price_query, search_results(price_query, max_results=6))


def _compare(items: list[str], aspect: str) -> str:
    """Search each comparison item independently and show the evidence per item."""
    clean_items = [str(item).strip() for item in items if str(item).strip()]
    if len(clean_items) < 2:
        return "Please provide at least two items to compare."

    lines = [f"Live search comparison — {aspect.upper()}", "─" * 40]
    for item in clean_items[:6]:
        lines.extend(["", f"▸ {item}"])
        try:
            results = search_results(f"{item} {aspect}", max_results=3)
        except Exception as exc:
            lines.append(f"  Live search failed: {exc}")
            continue
        if not results:
            lines.append("  No source-linked results were returned.")
            continue
        for result in results[:3]:
            if result.get("title"):
                lines.append(f"  • {result['title']}")
            if result.get("snippet"):
                lines.append(f"    {result['snippet']}")
            if result.get("url"):
                lines.append(f"    Source: {result['url']}")
    return "\n".join(lines)


def web_search(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    query = str(params.get("query") or "").strip()
    mode = str(params.get("mode") or "search").lower().strip()
    raw_items = params.get("items", [])
    items = raw_items if isinstance(raw_items, list) else []
    aspect = str(params.get("aspect") or "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."

    if items and mode != "compare":
        mode = "compare"

    if player:
        try:
            player.write_log(f"[Search:{mode}] {query or ', '.join(map(str, items))}")
        except Exception:
            pass

    print(f"[WebSearch] live mode={mode!r} query={query!r}")

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        return _search(query)
    except Exception as exc:
        print(f"[WebSearch] Live search failed: {exc}")
        return f"Live web search failed: {exc}"
