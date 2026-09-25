"""
Deep Source Research Service (roadmap v13, Feature B)

Keyless, privacy-preserving search across open-domain books, public archives, and
newspaper/news sources (India + abroad) for agents and the Research tab:
- Project Gutenberg (Gutendex) and Open Library for open-domain books.
- Internet Archive (texts) and Wikisource for public archives.
- GDELT, Google News (RSS), and Chronicling America for newspapers/news.

Mirrors app/services/web_research.py: anonymous keyless HTTP calls, the shared
query sanitizer, and a `[]`-on-failure contract so a dead provider never breaks
the aggregate result.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import requests

from app.services.web_research import sanitize_search_query

logger = logging.getLogger("buzzcaf_ai.deep_research")

DEFAULT_TIMEOUT = 10
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


# ───────────────────────── HTTP helpers (monkeypatch seams) ─────────────────────────

def _get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = DEFAULT_TIMEOUT) -> Optional[Any]:
    """GET a URL and parse JSON. Returns None on non-200 status or any exception."""
    try:
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as exc:
        logger.warning(f"GET (json) failed for {url}: {exc}")
        return None


def _get_text(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """GET a URL and return raw text. Returns '' on non-200 status or any exception."""
    try:
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return ""
        return resp.text
    except Exception as exc:
        logger.warning(f"GET (text) failed for {url}: {exc}")
        return ""


def _result(title: str, snippet: str, url: str, source: str, kind: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "title": title or "",
        "snippet": (snippet or "").strip(" —"),
        "url": url or "",
        "source": source,
        "kind": kind,
        "meta": meta or {},
    }


# ───────────────────────── Providers: Books ─────────────────────────

def search_gutenberg(q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search Project Gutenberg (via the Gutendex API) for open-domain books."""
    clean_q = sanitize_search_query(q)
    if not clean_q:
        return []
    try:
        data = _get_json("https://gutendex.com/books", params={"search": clean_q})
        if not data:
            return []
        results: List[Dict[str, Any]] = []
        for book in (data.get("results") or [])[:limit]:
            book_id = book.get("id")
            title = book.get("title", "")
            authors = book.get("authors") or []
            author_names = ", ".join(a.get("name", "") for a in authors if a.get("name"))
            subjects = book.get("subjects") or []
            subject_str = "; ".join(subjects[:3])
            snippet = " — ".join(p for p in (author_names, subject_str) if p)
            url = f"https://www.gutenberg.org/ebooks/{book_id}" if book_id is not None else ""
            results.append(_result(title, snippet, url, "Project Gutenberg", "book"))
        return results
    except Exception as exc:
        logger.warning(f"Gutenberg search failed for '{clean_q}': {exc}")
        return []


def search_open_library(q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search Open Library's catalog for open-domain and public-interest books."""
    clean_q = sanitize_search_query(q)
    if not clean_q:
        return []
    try:
        data = _get_json("https://openlibrary.org/search.json", params={"q": clean_q, "limit": limit})
        if not data:
            return []
        results: List[Dict[str, Any]] = []
        for doc in (data.get("docs") or [])[:limit]:
            title = doc.get("title", "")
            author_name = doc.get("author_name") or []
            first_publish_year = doc.get("first_publish_year")
            key = doc.get("key", "")
            snippet = ", ".join(author_name)
            if first_publish_year:
                snippet = f"{snippet} ({first_publish_year})" if snippet else f"({first_publish_year})"
            url = f"https://openlibrary.org{key}" if key else ""
            results.append(_result(title, snippet, url, "Open Library", "book"))
        return results
    except Exception as exc:
        logger.warning(f"Open Library search failed for '{clean_q}': {exc}")
        return []


# ───────────────────────── Providers: Archives ─────────────────────────

def search_internet_archive(q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search the Internet Archive's text collection (books, documents, ephemera)."""
    clean_q = sanitize_search_query(q)
    if not clean_q:
        return []
    try:
        data = _get_json(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"{clean_q} AND mediatype:texts",
                "fl[]": ["identifier", "title", "creator", "year", "description"],
                "rows": limit,
                "page": 1,
                "output": "json",
            },
        )
        if not data:
            return []
        docs = ((data.get("response") or {}).get("docs")) or []
        results: List[Dict[str, Any]] = []
        for doc in docs[:limit]:
            identifier = doc.get("identifier", "")
            title = doc.get("title", "")
            creator = doc.get("creator", "")
            year = doc.get("year", "")
            description = (doc.get("description") or "")[:200]
            snippet = " — ".join(str(p) for p in (creator, year, description) if p)
            url = f"https://archive.org/details/{identifier}" if identifier else ""
            results.append(_result(title, snippet, url, "Internet Archive", "archive"))
        return results
    except Exception as exc:
        logger.warning(f"Internet Archive search failed for '{clean_q}': {exc}")
        return []


def search_wikisource(q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search Wikisource (public-domain primary texts) using the opensearch API."""
    clean_q = sanitize_search_query(q)
    if not clean_q:
        return []
    try:
        data = _get_json(
            "https://en.wikisource.org/w/api.php",
            params={"action": "opensearch", "search": clean_q, "limit": limit, "namespace": 0, "format": "json"},
        )
        if not data:
            return []
        titles = data[1] if len(data) > 1 else []
        descriptions = data[2] if len(data) > 2 else []
        urls = data[3] if len(data) > 3 else []
        results: List[Dict[str, Any]] = []
        for title, desc, link in zip(titles, descriptions, urls):
            results.append(_result(title, desc, link, "Wikisource", "archive"))
        return results[:limit]
    except Exception as exc:
        logger.warning(f"Wikisource search failed for '{clean_q}': {exc}")
        return []


# ───────────────────────── Providers: News ─────────────────────────

def search_gdelt_news(q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search GDELT's global news index (covers India and international press)."""
    clean_q = sanitize_search_query(q)
    if not clean_q:
        return []
    try:
        data = _get_json(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": clean_q, "mode": "ArtList", "format": "json", "maxrecords": limit, "sort": "DateDesc"},
        )
        if not data:
            return []
        articles = data.get("articles") or []
        results: List[Dict[str, Any]] = []
        for art in articles[:limit]:
            title = art.get("title", "")
            url = art.get("url", "")
            domain = art.get("domain", "")
            seendate = art.get("seendate", "")
            sourcecountry = art.get("sourcecountry", "")
            snippet = f"{domain} — {sourcecountry} — {seendate}"
            results.append(_result(title, snippet, url, "GDELT", "news"))
        return results
    except Exception as exc:
        logger.warning(f"GDELT search failed for '{clean_q}': {exc}")
        return []


def search_google_news(q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search Google News RSS (India-focused edition) for recent coverage."""
    clean_q = sanitize_search_query(q)
    if not clean_q:
        return []
    try:
        text = _get_text(
            "https://news.google.com/rss/search",
            params={"q": clean_q, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
        )
        if not text:
            return []
        root = ET.fromstring(text)
        results: List[Dict[str, Any]] = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source_el = item.find("source")
            source_name = (source_el.text or "").strip() if source_el is not None and source_el.text else "Google News"
            snippet = f"{source_name} — {pub_date}"
            results.append(_result(title, snippet, link, "Google News", "news"))
        return results
    except Exception as exc:
        logger.warning(f"Google News search failed for '{clean_q}': {exc}")
        return []


def search_chronicling_america(q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search the Library of Congress's Chronicling America historic newspaper archive."""
    clean_q = sanitize_search_query(q)
    if not clean_q:
        return []
    try:
        data = _get_json(
            "https://chroniclingamerica.loc.gov/search/pages/results/",
            params={"andtext": clean_q, "format": "json", "rows": limit},
        )
        if not data:
            return []
        items = (data.get("items") or [])[:limit]
        results: List[Dict[str, Any]] = []
        for item in items:
            title = item.get("title_normal") or item.get("title") or ""
            date = item.get("date", "")
            item_id = item.get("id", "")
            ocr = (item.get("ocr_eng") or "")[:200]
            snippet = " — ".join(p for p in (date, ocr) if p)
            url = f"https://chroniclingamerica.loc.gov{item_id}" if item_id else ""
            results.append(_result(title, snippet, url, "Chronicling America", "news"))
        return results
    except Exception as exc:
        logger.warning(f"Chronicling America search failed for '{clean_q}': {exc}")
        return []


# ───────────────────────── Aggregators ─────────────────────────

KIND_PROVIDERS = {
    "news": [search_gdelt_news, search_google_news, search_chronicling_america],
    "archives": [search_internet_archive, search_wikisource],
    "books": [search_gutenberg, search_open_library],
}


def deep_research(
    query: str,
    kinds: Tuple[str, ...] = ("news", "archives", "books"),
    per_source: int = 5,
) -> Dict[str, Any]:
    """Fan out to keyless book/archive/news providers, dedupe by url, and group results.

    Never raises: config errors and provider failures degrade to an empty-shaped result.
    """
    empty: Dict[str, Any] = {
        "query": query,
        "results": [],
        "by_kind": {"news": [], "archives": [], "books": []},
        "sources_searched": [],
    }

    try:
        from integrations.llm import load_config
        if not load_config().get("web_research_enabled", True):
            return empty
    except Exception as exc:
        logger.warning(f"deep_research: could not load config, proceeding: {exc}")

    clean_q = sanitize_search_query(query)
    if not clean_q:
        return empty

    by_kind: Dict[str, List[Dict[str, Any]]] = {"news": [], "archives": [], "books": []}
    all_results: List[Dict[str, Any]] = []
    seen_urls = set()
    source_counts: Dict[str, int] = {}

    for kind in kinds:
        providers = KIND_PROVIDERS.get(kind, [])
        for provider in providers:
            try:
                items = provider(clean_q, per_source) or []
            except Exception as exc:
                logger.warning(f"deep_research: provider {getattr(provider, '__name__', provider)} raised: {exc}")
                items = []
            if not items:
                continue
            source_label = items[0].get("source") or getattr(provider, "__name__", "unknown")
            source_counts[source_label] = source_counts.get(source_label, 0) + len(items)
            for item in items:
                url = item.get("url", "")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                by_kind.setdefault(kind, []).append(item)
                all_results.append(item)

    sources_searched = [{"source": source, "count": count} for source, count in source_counts.items()]

    return {
        "query": clean_q,
        "results": all_results,
        "by_kind": by_kind,
        "sources_searched": sources_searched,
    }


def build_source_brief(
    query: str,
    kinds: Tuple[str, ...] = ("news", "archives", "books"),
    per_source: int = 4,
) -> str:
    """Build a Markdown dossier of book/archive/news sources for agent prompt injection."""
    data = deep_research(query, kinds=kinds, per_source=per_source)
    by_kind = data.get("by_kind") or {}
    if not data.get("results"):
        return ""

    clean_q = data.get("query") or sanitize_search_query(query)
    kind_labels = {"news": "News", "archives": "Archives", "books": "Books"}

    lines = [f"### Source Research Dossier ({clean_q})", ""]
    for kind in kinds:
        items = by_kind.get(kind) or []
        if not items:
            continue
        lines.append(f"**{kind_labels.get(kind, kind.title())}**")
        for item in items:
            title = item.get("title") or "Untitled"
            source = item.get("source", "")
            snippet = (item.get("snippet") or "").strip()
            url = item.get("url", "")
            bullet = f"- **{title}** ({source})"
            if snippet:
                bullet += f": {snippet}"
            if url:
                bullet += f" [{url}]"
            lines.append(bullet)
        lines.append("")

    return "\n".join(lines).strip()
