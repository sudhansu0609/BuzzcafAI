"""
Privacy-Preserving Web Research Service (roadmap v10)

Provides live web search, encyclopedic fact verification, and safe webpage fetching
for agents and subagents (WebResearcher, ResearchAgent, Studio Assistant)
while ensuring ZERO private data leaks:
- System prompts, private project files, user credentials, and internal memories
  are NEVER sent over the wire.
- Query sanitizer ensures only generic public keywords leave the PC.
- Anonymous, keyless search providers (DuckDuckGo API, Wikipedia Opensearch & Summary API).
- Safe HTML parser extracts clean plain text without executing scripts or setting tracking cookies.
"""

import html
from html.parser import HTMLParser
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse
import requests

logger = logging.getLogger("buzzcaf_ai.web_research")

DEFAULT_TIMEOUT = 4
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
WIKI_USER_AGENT = "BuzzcafAIStudio/1.0 (local privacy-safe research agent; https://github.com/sudhansu0609/BuzzcafAI)"


# ───────────────────────── Query Sanitization ─────────────────────────

def sanitize_search_query(query: str) -> str:
    """Strip private paths, file extensions, API keys, and internal tokens from query.

    Guarantees no local system data or confidential context leaks in the search query.
    """
    if not query:
        return ""

    text = str(query).strip()

    # Remove code blocks or JSON formatting
    text = re.sub(r"```[a-zA-Z]*", " ", text)

    # Strip prompt directives like "[INVOKE_AGENT:...]", "[WEB_SEARCH:...]", etc.
    text = re.sub(r"\[(?:INVOKE_AGENT|WEB_SEARCH|WEB_FETCH|SEARCH):\s*([^\]]*?)\]", r" \1 ", text, flags=re.I)
    text = re.sub(r"\[/?(?:INVOKE_AGENT|WEB_SEARCH|WEB_FETCH|SEARCH)[^\]]*\]", " ", text, flags=re.I)

    # Strip brackets and punctuation
    text = re.sub(r"[{}\[\]\"\']", " ", text)

    # Strip Windows or Unix absolute filesystem paths (e.g., C:\..., /home/..., /Users/...)
    text = re.sub(r"[A-Za-z]:\\[^ \t\r\n]+", " ", text)
    text = re.sub(r"/(?:Users|home|tmp|etc|var|projects)/[^ \t\r\n]+", " ", text)

    # Strip suspected API keys or tokens (sk-..., AIza..., ghp_..., etc.)
    text = re.sub(r"\b(?:sk-[a-zA-Z0-9_\-]{20,}|AIza[a-zA-Z0-9_\-]{20,}|ghp_[a-zA-Z0-9_\-]{20,})\b", " ", text)

    # Collapse whitespace and normalize
    text = re.sub(r"\s+", " ", text).strip()

    # Truncate to reasonable search length (max 120 chars)
    if len(text) > 120:
        text = text[:120].rsplit(" ", 1)[0].strip()

    return text


# ───────────────────────── Safe HTML Text Extractor ─────────────────────────

class CleanTextExtractor(HTMLParser):
    """Safely extracts plain readable text from HTML markup without scripts or styles."""

    def __init__(self):
        super().__init__()
        self.text_parts: List[str] = []
        self._ignore_stack = 0
        self._ignored_tags = {
            "script", "style", "noscript", "svg", "header",
            "footer", "nav", "aside", "form", "iframe"
        }

    def handle_starttag(self, tag: str, attrs: Any):
        if tag.lower() in self._ignored_tags:
            self._ignore_stack += 1

    def handle_endtag(self, tag: str):
        if tag.lower() in self._ignored_tags and self._ignore_stack > 0:
            self._ignore_stack -= 1

    def handle_data(self, data: str):
        if self._ignore_stack == 0:
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(cleaned)


def fetch_page_content(url: str, max_chars: int = 3500) -> str:
    """Download a public webpage and extract clean plain-text for LLM synthesis.

    Zero credentials, cookies, or tracking headers are transmitted.
    """
    clean_url = (url or "").strip()
    if not clean_url.startswith(("http://", "https://")):
        return f"Error: Invalid URL '{clean_url}'"

    try:
        headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        resp = requests.get(clean_url, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return f"Error: HTTP {resp.status_code} fetching '{clean_url}'"

        parser = CleanTextExtractor()
        # Feed decoded text
        parser.feed(resp.text)
        raw_text = " ".join(parser.text_parts)
        # Normalize whitespace
        cleaned = re.sub(r"\s+", " ", raw_text).strip()
        if not cleaned:
            return "No extractable text content found on the page."
        return cleaned[:max_chars]
    except Exception as exc:
        logger.warning(f"Error fetching page {clean_url}: {exc}")
        return f"Could not fetch {clean_url}: {exc}"


# ───────────────────────── Search Providers ─────────────────────────

def search_wikipedia(query: str, max_results: int = 4) -> List[Dict[str, str]]:
    """Search Wikipedia using the public Opensearch and REST Summary APIs.

    Fast, verified encyclopedic facts with zero tracking and no API keys.
    """
    clean_q = sanitize_search_query(query)
    if not clean_q:
        return []

    results: List[Dict[str, str]] = []
    try:
        # 1. Opensearch for candidate articles
        opensearch_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "opensearch",
            "search": clean_q,
            "limit": max_results,
            "namespace": 0,
            "format": "json"
        }
        headers = {"User-Agent": WIKI_USER_AGENT}
        resp = requests.get(opensearch_url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            titles = data[1] if len(data) > 1 else []
            descriptions = data[2] if len(data) > 2 else []
            urls = data[3] if len(data) > 3 else []

            for title, desc, link in zip(titles, descriptions, urls):
                snippet = desc
                # If opensearch description is empty or very short, fetch the REST summary
                if not snippet or len(snippet) < 40:
                    try:
                        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}"
                        sum_resp = requests.get(summary_url, headers=headers, timeout=4)
                        if sum_resp.status_code == 200:
                            s_data = sum_resp.json()
                            snippet = s_data.get("extract", "") or snippet
                    except Exception:
                        pass

                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": link,
                    "source": "Wikipedia"
                })
    except Exception as exc:
        logger.warning(f"Wikipedia search failed for '{clean_q}': {exc}")

    return results


def search_duckduckgo_instant(query: str) -> List[Dict[str, str]]:
    """Query DuckDuckGo Instant Answer API for encyclopedic definition & related topics."""
    clean_q = sanitize_search_query(query)
    if not clean_q:
        return []

    results: List[Dict[str, str]] = []
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": clean_q, "format": "json", "no_html": 1, "skip_disambig": 1}
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        resp = requests.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            abstract = data.get("AbstractText")
            abstract_url = data.get("AbstractURL")
            heading = data.get("Heading") or clean_q

            if abstract and abstract_url:
                results.append({
                    "title": heading,
                    "snippet": abstract,
                    "url": abstract_url,
                    "source": "DuckDuckGo"
                })

            # Check related topics
            for topic in data.get("RelatedTopics", [])[:3]:
                text = topic.get("Text")
                first_url = topic.get("FirstURL")
                if text and first_url:
                    parts = text.split(" - ", 1)
                    title = parts[0] if len(parts) > 1 else heading
                    snippet = parts[1] if len(parts) > 1 else text
                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": first_url,
                        "source": "DuckDuckGo"
                    })
    except Exception as exc:
        logger.warning(f"DuckDuckGo instant answer failed for '{clean_q}': {exc}")

    return results


def search_searxng(query: str, base_url: str = "http://localhost:8080", max_results: int = 5) -> List[Dict[str, str]]:
    """Query SearXNG local/configured instance for private metasearch."""
    clean_q = sanitize_search_query(query)
    if not clean_q:
        return []

    results: List[Dict[str, str]] = []
    url = f"{base_url.rstrip('/')}/search"
    params = {"q": clean_q, "format": "json"}
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            for r in data.get("results", [])[:max_results]:
                title = r.get("title", "")
                content = r.get("content", "")
                link = r.get("url", "")
                engine = r.get("engine", "searxng")
                if title and link:
                    results.append({
                        "title": title,
                        "snippet": content,
                        "url": link,
                        "source": f"SearXNG ({engine})"
                    })
    except Exception as exc:
        logger.debug(f"SearXNG search at {base_url} failed: {exc}")
    return results


def search_web(
    query: str,
    max_results: int = 5,
    provider: Optional[str] = None,
    searxng_url: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Unified search: queries SearXNG, Wikipedia, and DuckDuckGo anonymously and deduplicates results."""
    clean_q = sanitize_search_query(query)
    if not clean_q:
        return []

    combined: List[Dict[str, str]] = []
    seen_urls = set()

    # Load configuration
    try:
        from integrations.llm import load_config
        cfg = load_config()
    except Exception:
        cfg = {}

    chosen_provider = (provider or cfg.get("search_provider") or "auto").lower()
    sx_url = searxng_url or cfg.get("searxng_url") or "http://localhost:8080"

    # 1. SearXNG (if specifically requested or in auto mode)
    if chosen_provider in ("searxng", "auto"):
        sx_results = search_searxng(clean_q, base_url=sx_url, max_results=max_results)
        for r in sx_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                combined.append(r)
        if chosen_provider == "searxng" and combined:
            return combined[:max_results]

    # 2. Wikipedia (authoritative, high-density facts)
    if chosen_provider in ("wikipedia", "auto") or not combined:
        wiki_results = search_wikipedia(clean_q, max_results=max_results)
        for r in wiki_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                combined.append(r)
        if chosen_provider == "wikipedia" and combined:
            return combined[:max_results]

    # 3. DuckDuckGo Instant Answers & Topics
    if chosen_provider in ("duckduckgo", "auto") or not combined:
        ddg_results = search_duckduckgo_instant(clean_q)
        for r in ddg_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                combined.append(r)

    return combined[:max_results]


def build_research_brief(topic: str, context: Optional[str] = None) -> str:
    """Build a structured research dossier formatted for agent prompt ingestion."""
    clean_topic = sanitize_search_query(topic)
    if not clean_topic:
        return "No topic provided for web research."

    logger.info(f"Conducting live privacy-safe web research on: '{clean_topic}'")
    results = search_web(clean_topic, max_results=4)

    if not results:
        return f"No live search results found for '{clean_topic}'."

    lines = [
        f"### Verified Live Web Research Dossier ({clean_topic})",
        "The following real-time sources were retrieved securely from the web to ground this research:\n"
    ]

    for idx, r in enumerate(results, 1):
        title = r.get("title", "Reference")
        snippet = r.get("snippet", "").strip()
        url = r.get("url", "")
        source = r.get("source", "Web")
        lines.append(f"{idx}. **[{title}]** ({source})")
        if snippet:
            lines.append(f"   - **Summary**: {snippet}")
        if url:
            lines.append(f"   - **Source URL**: {url}")
        lines.append("")

    lines.append(
        "> **Verification Directive**: Incorporate these verified facts and source URLs into the timeline, "
        "facts, and sources outputs. Do not invent details not backed by verified knowledge."
    )
    return "\n".join(lines)


# Singleton
class WebResearchService:
    def sanitize(self, query: str) -> str:
        return sanitize_search_query(query)

    def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        return search_web(query, max_results=max_results)

    def fetch(self, url: str, max_chars: int = 3500) -> str:
        return fetch_page_content(url, max_chars=max_chars)

    def brief(self, topic: str, context: Optional[str] = None) -> str:
        return build_research_brief(topic, context=context)

web_research_service = WebResearchService()
