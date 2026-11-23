"""Story Library: rights rule, Gutenberg stripping, language detection, search
merging with the network faked, the 60k-word refusal, and the routes."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.services import story_library as sl


@pytest.fixture(autouse=True)
def lib_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sl, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(sl, "wikidata_lookup", lambda author: pytest.fail("network used"))
    return tmp_path / "library"


# ── rights ──

def test_rights_rule_by_year():
    assert sl.verdict_for_year(1965, 2026) == "public_domain"
    assert sl.verdict_for_year(1936, 2026) == "public_domain"
    assert sl.verdict_for_year(1966, 2026) == "protected"
    assert sl.verdict_for_year(2008, 2026) == "protected"
    assert sl.verdict_for_year(None, 2026) == "unknown"


def test_rights_for_uses_wikidata_and_caches(monkeypatch, lib_dir):
    calls = []

    def fake(author):
        calls.append(author)
        return {"1": {"death_year": 1936, "qid": "Q1", "label": "M. R. James"},
                "2": {"death_year": 2008, "qid": "Q2", "label": "X"},
                "3": {"death_year": None, "qid": "Q3", "label": "Y"}}[author[-1]]

    monkeypatch.setattr(sl, "wikidata_lookup", fake)
    assert sl.rights_for("Writer 1")["status"] == "public_domain"
    assert sl.rights_for("Writer 1")["status"] == "public_domain"
    assert calls == ["Writer 1"]  # second answer from the cache
    assert sl.rights_for("Writer 2")["status"] == "protected"
    unknown = sl.rights_for("Writer 3")
    assert unknown["status"] == "unknown" and unknown["death_year"] is None
    cache = json.loads((lib_dir / "_authors.json").read_text(encoding="utf-8"))
    assert set(cache) == {"writer 1", "writer 2", "writer 3"}


def test_rights_unreachable_is_not_cached(monkeypatch, lib_dir):
    monkeypatch.setattr(sl, "wikidata_lookup", lambda a: None)
    assert sl.rights_for("Somebody")["status"] == "unknown"
    assert not (lib_dir / "_authors.json").exists()


def test_known_protected_list_needs_no_network():
    for name in ("Narayan Dharap", "Ratnakar Matkari", "Stephen King", "King, Stephen"):
        assert sl.rights_for(name)["status"] == "protected"
    assert sl.rights_for("Narayan Dharap")["death_year"] == 2008
    assert "shirley jackson" not in sl.KNOWN_PROTECTED


def test_no_author_is_unknown():
    assert sl.rights_for("")["status"] == "unknown"
    assert sl.rights_for("Anonymous")["status"] == "unknown"


# ── text ──

GUTENBERG_SAMPLE = """﻿The Project Gutenberg eBook of Ghost Stories of an Antiquary\r
\r
This ebook is for the use of anyone anywhere.\r
\r
*** START OF THE PROJECT GUTENBERG EBOOK GHOST STORIES OF AN ANTIQUARY ***\r
\r
Produced by Somebody and the Online Distributed Proofreaders.\r
\r
CANON ALBERIC'S SCRAP-BOOK\r
\r
St Bertrand de Comminges is a decayed town on the spurs of the Pyrenees.\r
\r
*** END OF THE PROJECT GUTENBERG EBOOK GHOST STORIES OF AN ANTIQUARY ***\r
\r
Section 1. General Terms of Use\r
"""


def test_strip_gutenberg_header_and_footer():
    text = sl.strip_gutenberg(GUTENBERG_SAMPLE)
    assert text.startswith("CANON ALBERIC'S SCRAP-BOOK")
    assert text.endswith("spurs of the Pyrenees.")
    assert "Project Gutenberg" not in text and "Produced by" not in text and "\r" not in text


def test_strip_gutenberg_old_footer():
    raw = "*** START OF THIS PROJECT GUTENBERG EBOOK X ***\n\nThe tale.\n\nEnd of the Project Gutenberg EBook of X\nlicence"
    assert sl.strip_gutenberg(raw) == "The tale."


def test_detect_language():
    assert sl.detect_language("रात के तीन बजे दरवाज़ा अपने आप खुला।") == "hi"
    assert sl.detect_language("रात्री तीन वाजता दार उघडले.", hint="mr") == "mr"
    assert sl.detect_language("রাত তিনটের সময় দরজা খুলে গেল।") == "bn"
    assert sl.detect_language("The door opened by itself at three in the night.") == "en"
    assert sl.detect_language("12345 ...") == "unknown"


def test_wikitext_and_html_cleaning():
    wt = "{{header|title=X|author=[[Author:Bram Stoker|Bram Stoker]]}}\n''The'' [[Dracula|count]] came.<ref>n</ref>"
    assert sl.wikitext_to_text(wt) == "The count came."
    assert sl._wikisource_author(wt) == "Bram Stoker"
    html = '<div class="ws-noexport">nav</div><p>One <sup>[1]</sup>night.</p><p>Two.</p>'
    assert sl.html_to_text(html) == "One night.\n\nTwo."


# ── search ──

def _fake_sources(monkeypatch):
    def gut(query, language="any", author="", limit=8):
        return [{"title": "Ghost Stories of an Antiquary", "author": "M. R. James", "language": "en",
                 "source": "gutenberg", "url": "https://www.gutenberg.org/ebooks/8486", "text_url": "",
                 "snippet": "Ghost stories", "tags": ["Ghost stories"], "death_year": 1936, "words_estimate": None}]

    def wiki(query, language="en", author="", limit=8):
        return [{"title": "Ghost Stories of an Antiquary", "author": "M. R. James", "language": "en",
                 "source": "wikisource", "url": "https://en.wikisource.org/wiki/Ghost_Stories_of_an_Antiquary",
                 "page": "Ghost Stories of an Antiquary", "snippet": "", "tags": [], "death_year": None,
                 "words_estimate": 50000},
                {"title": "Oh, Whistle, and I'll Come to You, My Lad", "author": "", "language": "en",
                 "source": "wikisource", "url": "https://en.wikisource.org/wiki/Oh_Whistle",
                 "page": "Oh Whistle", "snippet": "a ghost story", "tags": [], "death_year": None,
                 "words_estimate": 9000}]

    def arch(query, language="any", author="", limit=8):
        return [{"title": "Collected ghost stories", "author": "M. R. James", "language": "en",
                 "source": "archive", "url": "https://archive.org/details/collected", "identifier": "collected",
                 "snippet": "", "tags": [], "death_year": None, "words_estimate": None}]

    def boom(query, language="any", author="", limit=8):
        raise RuntimeError("down")

    monkeypatch.setattr(sl, "search_gutendex", gut)
    monkeypatch.setattr(sl, "search_wikisource", wiki)
    monkeypatch.setattr(sl, "search_archive", arch)
    monkeypatch.setattr(sl, "search_web", boom)


def test_search_merges_dedupes_and_ranks(monkeypatch):
    _fake_sources(monkeypatch)
    said = []
    out = sl.search("ghost story", language="en", author="M. R. James", limit=8, progress=said.append)
    titles = [(c["source"], c["title"]) for c in out]
    # the Wikisource copy of the same work by the same author is dropped
    assert titles.count(("wikisource", "Ghost Stories of an Antiquary")) == 0
    assert out[0]["source"] == "gutenberg"
    assert out[0]["rights"]["status"] == "public_domain"
    assert {c["source"] for c in out} == {"gutenberg", "wikisource", "archive"}
    assert all("rights" in c and "words_estimate" in c for c in out)
    assert said and "Searching web" in said


def test_search_uses_web_research_service(monkeypatch):
    from app.services import web_research

    monkeypatch.setattr(web_research.web_research_service, "search",
                        lambda q, max_results=5: [{"title": "A tale", "url": "https://x.org/a", "snippet": "s"},
                                                  {"title": "Dup", "url": "https://www.x.org/a/", "snippet": ""}])
    out = sl.search("bhoot", language="hi", source="web", limit=5)
    assert len(out) == 1 and out[0]["source"] == "web" and out[0]["language"] == "hi"


def test_search_limit_and_bad_source(monkeypatch):
    _fake_sources(monkeypatch)
    assert len(sl.search("ghost", limit=2)) == 2
    with pytest.raises(ValueError):
        sl.search("ghost", source="library_of_alexandria")
    with pytest.raises(ValueError):
        sl.search("", author="")


# ── fetch ──

def _cand(**kw):
    base = {"title": "Lost Hearts", "author": "M. R. James", "language": "en", "source": "gutenberg",
            "url": "https://www.gutenberg.org/ebooks/8486", "snippet": "", "tags": ["Ghost stories"],
            "death_year": 1936}
    base.update(kw)
    return base


def test_fetch_refuses_over_60k_words(monkeypatch, lib_dir):
    monkeypatch.setattr(sl, "fetch_gutenberg_text", lambda c: "word " * 60_001)
    with pytest.raises(ValueError, match="60,000"):
        sl.fetch(_cand())
    assert not (lib_dir / "index.json").exists()


def test_fetch_stores_entry_with_provenance(monkeypatch, lib_dir):
    story = "LOST HEARTS\n\n" + ("It was in September of the year 1811 that a post-chaise drew up. " * 40)
    monkeypatch.setattr(sl, "fetch_gutenberg_text", lambda c: story)
    monkeypatch.setattr(sl, "wikidata_lookup", lambda a: {"death_year": 1936, "qid": "Q1", "label": "M. R. James"})
    meta = sl.fetch(_cand())
    assert meta["rights"]["status"] == "public_domain" and meta["rights"]["source"] == "wikidata"
    assert meta["language"] == "en" and meta["words"] > 400
    assert set(meta) >= {"id", "title", "author", "language", "source", "source_url", "fetched_at", "words",
                         "rights", "summary", "tags", "first_lines"}
    assert meta["first_lines"].startswith("LOST HEARTS")
    assert (lib_dir / meta["id"] / "story.txt").read_text(encoding="utf-8").startswith("LOST HEARTS")
    assert sl.entries()[0]["id"] == meta["id"]
    assert sl.entry(meta["id"])["text"].startswith("LOST HEARTS")
    assert sl.delete(meta["id"]) and sl.entries() == [] and sl.entry(meta["id"]) is None
    assert sl.delete("../etc") is False


def test_fetch_refuses_empty_text(monkeypatch):
    monkeypatch.setattr(sl, "fetch_archive_text", lambda c: "")
    with pytest.raises(ValueError, match="Could not get"):
        sl.fetch(_cand(source="archive", url="https://archive.org/details/x"))


# ── routes ──

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_routes(monkeypatch, client):
    monkeypatch.setattr(sl, "search", lambda q, progress=None, **kw: [{"title": q, **kw}])
    monkeypatch.setattr(sl, "fetch", lambda c: {"id": "x-1", **c})
    monkeypatch.setattr(sl, "entries", lambda: [{"id": "x-1"}])
    monkeypatch.setattr(sl, "entry", lambda i: {"id": i, "text": "a" * 5000} if i == "x-1" else None)
    monkeypatch.setattr(sl, "delete", lambda i: i == "x-1")
    monkeypatch.setattr(sl, "rights_for", lambda a: {"status": "public_domain", "author": a})

    from integrations import idle_offload
    monkeypatch.setattr(idle_offload, "offload_now", lambda reason="": False)

    job = client.post("/api/stories/search", json={"query": "ghost", "language": "en"}).json()
    for _ in range(50):
        got = client.get(f"/api/stories/jobs/{job['job_id']}").json()
        if got["state"] != "running":
            break
        time.sleep(0.05)
    assert got["state"] == "done" and got["result"][0]["title"] == "ghost"
    assert got["result"][0]["language"] == "en"
    assert client.get("/api/stories/jobs/nope").status_code == 404
    assert client.post("/api/stories/search", json={"query": ""}).status_code == 400

    assert client.post("/api/stories/fetch", json={"candidate": {"title": "t"}}).json()["id"] == "x-1"
    assert client.get("/api/stories/library").json() == {"entries": [{"id": "x-1"}]}
    one = client.get("/api/stories/library/x-1").json()
    assert len(one["text"]) == 3000 and one["text_chars"] == 5000
    assert client.get("/api/stories/library/zz").status_code == 404
    assert client.delete("/api/stories/library/x-1").json() == {"deleted": "x-1"}
    assert client.delete("/api/stories/library/zz").status_code == 404
    assert client.get("/api/stories/rights", params={"author": "M. R. James"}).json()["status"] == "public_domain"
    assert client.get("/api/stories/rights").status_code == 400


def test_fetch_route_maps_refusal_to_422(monkeypatch, client):
    def refuse(c):
        raise ValueError("too long")
    monkeypatch.setattr(sl, "fetch", refuse)
    resp = client.post("/api/stories/fetch", json={"candidate": {"title": "t"}})
    assert resp.status_code == 422 and "too long" in resp.json()["detail"]
