"""
Deep source research (v13): each provider parser maps its payload to the shared
normalized shape, and deep_research fans out, dedupes by url, and reports what it
searched. No network -- the HTTP seams and providers are monkeypatched.
"""

import pytest

from app.services import deep_research as dr


def test_gutenberg_parses_gutendex(monkeypatch):
    payload = {"results": [{"id": 1342, "title": "Pride and Prejudice", "authors": [{"name": "Austen, Jane"}], "subjects": ["England -- Fiction"]}]}
    monkeypatch.setattr(dr, "_get_json", lambda url, params=None, timeout=10: payload)
    out = dr.search_gutenberg("pride", limit=5)
    assert len(out) == 1
    r = out[0]
    assert r["title"] == "Pride and Prejudice" and r["kind"] == "book" and r["source"] == "Project Gutenberg"
    assert r["url"] == "https://www.gutenberg.org/ebooks/1342"
    assert "Austen" in r["snippet"]


def test_google_news_parses_rss(monkeypatch):
    rss = (
        '<?xml version="1.0"?><rss><channel>'
        '<item><title>Flood hits city</title><link>http://news/1</link>'
        '<pubDate>Mon, 01 Jan 2026</pubDate><source url="http://x">The Times</source></item>'
        '</channel></rss>'
    )
    monkeypatch.setattr(dr, "_get_text", lambda url, params=None, timeout=10: rss)
    out = dr.search_google_news("flood", limit=5)
    assert len(out) == 1 and out[0]["kind"] == "news" and out[0]["url"] == "http://news/1"
    assert "The Times" in out[0]["snippet"]


def test_provider_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(dr, "_get_json", lambda *a, **k: None)
    assert dr.search_open_library("anything") == []
    assert dr.search_internet_archive("anything") == []


def test_deep_research_fans_out_dedupes_and_counts(monkeypatch):
    monkeypatch.setattr("integrations.llm.load_config", lambda: {"web_research_enabled": True})
    monkeypatch.setattr(dr, "KIND_PROVIDERS", {
        "news": [
            lambda q, n: [dr._result("N1", "", "http://a", "GDELT", "news")],
            lambda q, n: [dr._result("N1 dup", "", "http://a", "Google News", "news"), dr._result("N2", "", "http://b", "Google News", "news")],
            lambda q, n: [],
        ],
        "archives": [lambda q, n: [dr._result("A1", "", "http://c", "Internet Archive", "archive")], lambda q, n: []],
        "books": [lambda q, n: [dr._result("B1", "", "http://d", "Project Gutenberg", "book")], lambda q, n: []],
    })
    out = dr.deep_research("floods", kinds=("news", "archives", "books"), per_source=5)
    # The second http://a is deduped away; order preserved.
    assert [r["url"] for r in out["results"]] == ["http://a", "http://b", "http://c", "http://d"]
    assert len(out["by_kind"]["news"]) == 2 and len(out["by_kind"]["archives"]) == 1 and len(out["by_kind"]["books"]) == 1
    counts = {s["source"]: s["count"] for s in out["sources_searched"]}
    assert counts["GDELT"] == 1 and counts["Google News"] == 2


def test_deep_research_respects_disabled_flag(monkeypatch):
    monkeypatch.setattr("integrations.llm.load_config", lambda: {"web_research_enabled": False})
    out = dr.deep_research("floods")
    assert out["results"] == [] and out["sources_searched"] == []
