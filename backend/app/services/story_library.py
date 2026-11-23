"""
The Story Library (2026-10-23): horror stories by real writers, in any language,
found on keyless sources, fetched in full, with the rights decided and the
provenance kept.

    search(query, language=, author=, source=, limit=)  -> candidates
    fetch(candidate)                                    -> library entry
    entries() / entry(id) / delete(id)
    rights_for(author)                                  -> India rule, via Wikidata

Sources: Project Gutenberg (Gutendex), Wikisource (any language subdomain),
the Internet Archive (texts) and the Studio's own web search
(`web_research_service`). Each source search is one request; the fetchers are
module-level names so tests can replace them.

Rights (India): a work is public domain when its author died in or before
`current year - 61`; otherwise it is protected; no death date known means
`unknown`, which is treated as protected. Verdicts are cached in
`knowledge/stories/library/_authors.json`.

Storage: `knowledge/stories/library/<id>/story.txt` + `meta.json`
`{id, title, author, language, source, source_url, fetched_at, words, rights,
summary, tags, first_lines}`, listed in `index.json`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import uuid
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import requests

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.story_library")

LIBRARY_DIR = Path(KNOWLEDGE_DIR) / "stories" / "library"
TIMEOUT = 20
USER_AGENT = "BuzzcafStudio/1.0 (story library; local research tool; contact: studio owner)"
MAX_WORDS = 60_000
MIN_WORDS = 80
PD_AFTER_YEARS = 61  # India: life + 60 years, counted from the year after death

SOURCES = ("gutenberg", "wikisource", "archive", "web")
SOURCE_WEIGHT = {"gutenberg": 2.0, "wikisource": 1.5, "archive": 1.0, "web": 0.0}

# Safety net: names that stay protected whatever a lookup says.
KNOWN_PROTECTED: Dict[str, Optional[int]] = {
    "narayan dharap": 2008,
    "ratnakar matkari": 2020,
    "stephen king": None,
}

ARCHIVE_LANG = {"en": "eng", "hi": "hin", "mr": "mar", "bn": "ben", "ur": "urd", "gu": "guj",
                "ta": "tam", "te": "tel", "kn": "kan", "ml": "mal", "pa": "pan"}

ProgressFn = Optional[Callable[[str], None]]

_lock = threading.Lock()


# ──────────────────────────── small helpers ────────────────────────────

def _say(progress: ProgressFn, msg: str) -> None:
    if progress:
        try:
            progress(msg)
        except Exception:  # noqa: BLE001 - progress is cosmetic
            pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _lib() -> Path:
    path = Path(LIBRARY_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - missing or broken file
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _http_get(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            logger.info("story library: HTTP %s for %s", resp.status_code, url)
            return None
        return resp
    except Exception as exc:  # noqa: BLE001 - a dead source is skipped
        logger.info("story library: %s failed: %s", url, exc)
        return None


def _get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    resp = _http_get(url, params)
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _get_text(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    resp = _http_get(url, params)
    if resp is None:
        return ""
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text or ""


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def flip_name(name: str) -> str:
    """'James, M. R. (Montague Rhodes)' -> 'M. R. James'."""
    name = re.sub(r"\s*\([^)]*\)", "", (name or "")).strip()
    if "," in name:
        last, _, first = name.partition(",")
        if first.strip() and not re.search(r"\d", first):
            return f"{first.strip()} {last.strip()}"
    return name


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


# ──────────────────────────── text cleaning ────────────────────────────

_GUT_START = re.compile(r"^\s*\*{3}\s*START OF (THE|THIS) PROJECT GUTENBERG.*$", re.I | re.M)
_GUT_END = re.compile(r"^\s*\*{3}\s*END OF (THE|THIS) PROJECT GUTENBERG.*$", re.I | re.M)
_GUT_END_OLD = re.compile(r"^\s*End of (the )?Project Gutenberg'?s?.*$", re.I | re.M)


def strip_gutenberg(text: str) -> str:
    """Cut a Project Gutenberg file down to the work: the licence header before
    `*** START OF ... ***`, the footer from `*** END OF ... ***` (or the older
    'End of the Project Gutenberg EBook' line), and a leading 'Produced by' credit."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    start = _GUT_START.search(text)
    if start:
        text = text[start.end():]
    end = _GUT_END.search(text) or _GUT_END_OLD.search(text)
    if end:
        text = text[:end.start()]
    paras = re.split(r"\n\s*\n", text.strip())
    while paras and re.match(r"^\s*(Produced by|Transcribed from|E-text prepared by|This e-?book was produced)",
                             paras[0], re.I):
        paras.pop(0)
    return "\n\n".join(p.strip("\n") for p in paras).strip()


class _HtmlText(HTMLParser):
    """HTML -> text with paragraph breaks; skips scripts, styles, edit links,
    references and the Wikisource header/navigation boxes."""

    SKIP = {"script", "style", "sup", "table", "noscript"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "tr", "poem", "blockquote"}
    SKIP_CLASSES = ("ws-noexport", "mw-editsection", "reference", "noprint", "ws-header", "headertemplate",
                    "pagenum", "ws-pagenum", "mw-references", "navbox")

    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self._skip: List[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        classes = " ".join(v or "" for k, v in attrs if k in ("class", "id")).lower()
        if self._skip:
            if tag not in ("br",):
                self._skip.append(tag)
            return
        if tag in self.SKIP or any(c in classes for c in self.SKIP_CLASSES):
            if tag != "br":
                self._skip.append(tag)
            return
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            if tag in self._skip:
                while self._skip and self._skip.pop() != tag:
                    pass
            return
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HtmlText()
    try:
        parser.feed(html or "")
    except Exception:  # noqa: BLE001 - keep what parsed
        pass
    raw = "".join(parser.parts)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in raw.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def wikitext_to_text(wikitext: str) -> str:
    """Rough wikitext -> text, for when the rendered page is unavailable."""
    text = re.sub(r"<ref[^>]*?/>|<ref[^>]*>.*?</ref>", "", wikitext or "", flags=re.S)
    for _ in range(6):  # nested templates, innermost first
        new = re.sub(r"\{\{[^{}]*\}\}", "", text)
        if new == text:
            break
        text = new
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^[=]+\s*(.*?)\s*[=]+\s*$", r"\1", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _wikisource_author(wikitext: str) -> str:
    m = re.search(r"\|\s*author\s*=\s*(\[\[[^\]]*\]\]|[^|\n}]+)", wikitext or "", re.I)
    if not m:
        return ""
    name = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", m.group(1)).strip()
    return re.sub(r"^(Author|लेखक|লেখক):", "", name).strip()


def detect_language(text: str, hint: str = "") -> str:
    """Script ratio over letters: Devanagari -> 'hi' (or the hint, e.g. 'mr'),
    Bengali -> 'bn', Latin -> 'en' (or a Latin-script hint). 'unknown' when no
    script holds 50% of the letters."""
    sample = (text or "")[:20000]
    deva = len(re.findall(r"[ऀ-ॿ]", sample))
    beng = len(re.findall(r"[ঀ-৿]", sample))
    latin = len(re.findall(r"[A-Za-zÀ-ɏ]", sample))
    total = deva + beng + latin
    if not total:
        return "unknown"
    hint = (hint or "").lower()
    if deva / total >= 0.5:
        return hint if hint in ("hi", "mr", "ne", "sa") else "hi"
    if beng / total >= 0.5:
        return hint if hint in ("bn", "as") else "bn"
    if latin / total >= 0.5:
        return hint if hint and hint not in ("any", "hi", "mr", "ne", "sa", "bn", "as") else "en"
    return "unknown"


# ──────────────────────────── rights ────────────────────────────

def verdict_for_year(death_year: Optional[int], year: Optional[int] = None) -> str:
    """The India rule: public domain when the author died in or before
    `year - 61`; protected after; unknown when no death year is known."""
    if death_year is None:
        return "unknown"
    year = year or datetime.now().year
    return "public_domain" if int(death_year) <= year - PD_AFTER_YEARS else "protected"


def _authors_path() -> Path:
    return _lib() / "_authors.json"


def _known(author: str) -> Optional[Dict[str, Any]]:
    key = _norm(flip_name(author))
    if key in KNOWN_PROTECTED:
        return {"status": "protected", "death_year": KNOWN_PROTECTED[key], "source": "known_protected",
                "note": "On the known-protected list"}
    return None


def _year_of(time_value: str) -> Optional[int]:
    m = re.match(r"^([+-])(\d+)-", time_value or "")
    if not m:
        return None
    year = int(m.group(2))
    return -year if m.group(1) == "-" else year


def wikidata_lookup(author: str) -> Optional[Dict[str, Any]]:
    """Two requests: wbsearchentities, then wbgetentities for P570 (date of
    death) on the first human hit. None when Wikidata cannot be reached."""
    lang = "hi" if re.search(r"[ऀ-ॿ]", author) else ("bn" if re.search(r"[ঀ-৿]", author) else "en")
    found = _get_json("https://www.wikidata.org/w/api.php",
                      {"action": "wbsearchentities", "search": author, "language": lang, "uselang": lang,
                       "type": "item", "limit": 7, "format": "json"})
    if found is None:
        return None
    ids = [row.get("id") for row in (found.get("search") or []) if row.get("id")]
    if not ids:
        return {"death_year": None, "qid": None, "label": ""}
    data = _get_json("https://www.wikidata.org/w/api.php",
                     {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels",
                      "languages": "en", "format": "json"})
    if data is None:
        return None
    entities = data.get("entities") or {}
    for qid in ids:
        ent = entities.get(qid) or {}
        claims = ent.get("claims") or {}
        human = any(((c.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id") == "Q5"
                    for c in claims.get("P31") or [])
        if not human:
            continue
        label = ((ent.get("labels") or {}).get("en") or {}).get("value", "")
        for claim in claims.get("P570") or []:
            value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
            year = _year_of(value.get("time", ""))
            if year is not None:
                return {"death_year": year, "qid": qid, "label": label}
        return {"death_year": None, "qid": qid, "label": label}
    return {"death_year": None, "qid": None, "label": ""}


def rights_for(author: str) -> Dict[str, Any]:
    """{status: public_domain|protected|unknown, death_year, source, note}.
    Known-protected names first, then the cache, then Wikidata. A lookup that
    could not reach Wikidata is not cached."""
    # Library catalogues (Internet Archive, Gutenberg) write "Tagore, Rabindranath,
    # 1861-1941" or "Jacobs, W. W., 1863-1943, author": the dates are the answer, and
    # the dated string never matched on Wikidata (2026-10-23: Tagore came out
    # "protected"). Read them, and look the bare name up otherwise.
    dated = re.search(r"(\d{3,4})\??\s*[-–]\s*(\d{4})\??", author or "")
    if dated:
        death = int(dated.group(2))
        status = verdict_for_year(death)
        verb = "public domain in India" if status == "public_domain" else f"protected in India until {death + PD_AFTER_YEARS}"
        return {"status": status, "death_year": death, "source": "catalogue",
                "note": f"Died {death} (catalogue dates): {verb}"}
    author = re.sub(r",?\s*\b(author|editor|translator|illustrator)\b\.?", "", author or "", flags=re.I)
    author = flip_name(author).strip()
    if not author or _norm(author) in ("anonymous", "unknown", "various"):
        return {"status": "unknown", "death_year": None, "source": "none",
                "note": "No author named: treated as protected"}
    known = _known(author)
    if known:
        return known
    key = _norm(author)
    with _lock:
        cache = _read(_authors_path(), {})
    if key in cache:
        cached = dict(cache[key])
        cached.pop("checked_at", None)
        cached["status"] = verdict_for_year(cached.get("death_year")) if cached.get("death_year") is not None \
            else cached.get("status", "unknown")
        return cached
    hit = wikidata_lookup(author)
    if hit is None:
        return {"status": "unknown", "death_year": None, "source": "unreachable",
                "note": "Wikidata could not be reached: treated as protected"}
    death = hit.get("death_year")
    status = verdict_for_year(death)
    if status == "public_domain":
        note = f"Died {death}: public domain in India (death year <= {datetime.now().year - PD_AFTER_YEARS})"
    elif status == "protected":
        note = f"Died {death}: protected in India until {death + PD_AFTER_YEARS}"
    else:
        note = "No date of death on Wikidata: treated as protected"
    if hit.get("qid"):
        note += f" ({hit['qid']}{', ' + hit['label'] if hit.get('label') else ''})"
    verdict = {"status": status, "death_year": death, "source": "wikidata", "note": note}
    with _lock:
        cache = _read(_authors_path(), {})
        cache[key] = {**verdict, "checked_at": _now()}
        _write(_authors_path(), cache)
    return verdict


def quick_rights(author: str, death_year: Optional[int] = None, source: str = "") -> Dict[str, Any]:
    """No network: the known list, the cache, or a death year the source gave."""
    author = flip_name(author or "").strip()
    known = _known(author) if author else None
    if known:
        return known
    if author:
        cache = _read(_authors_path(), {})
        cached = cache.get(_norm(author))
        if cached:
            out = {k: v for k, v in cached.items() if k != "checked_at"}
            if out.get("death_year") is not None:
                out["status"] = verdict_for_year(out["death_year"])
            return out
    if death_year is not None:
        return {"status": verdict_for_year(death_year), "death_year": death_year, "source": source or "catalogue",
                "note": f"Death year {death_year} from the {source or 'catalogue'} record"}
    return {"status": "unknown", "death_year": None, "source": "unchecked",
            "note": "Not checked yet: fetch decides" if author else "No author named: treated as protected"}


# ──────────────────────────── source searches ────────────────────────────

def search_gutendex(query: str, language: str = "any", author: str = "", limit: int = 8) -> List[Dict[str, Any]]:
    """One request. With an author the author's books are listed and ranked by
    the query words (Gutendex wants every word to match)."""
    params: Dict[str, Any] = {"search": (author or query).strip()}
    if language and language != "any":
        params["languages"] = language
    data = _get_json("https://gutendex.com/books", params)
    out: List[Dict[str, Any]] = []
    for book in (data or {}).get("results") or []:
        if book.get("copyright") is True:
            continue
        people = book.get("authors") or []
        first = people[0] if people else {}
        formats = book.get("formats") or {}
        text_url = ""
        for mime, url in formats.items():
            if mime.startswith("text/plain") and not url.endswith(".zip"):
                text_url = url
                if "utf-8" in mime.lower():
                    break
        langs = book.get("languages") or []
        tags = [s for s in (book.get("subjects") or []) + (book.get("bookshelves") or [])][:8]
        out.append({
            "title": book.get("title") or "",
            "author": flip_name(first.get("name", "")),
            "language": langs[0] if langs else (language if language != "any" else ""),
            "source": "gutenberg",
            "url": f"https://www.gutenberg.org/ebooks/{book.get('id')}",
            "text_url": text_url,
            "snippet": "; ".join(tags[:4]),
            "tags": tags,
            "death_year": first.get("death_year"),
            "words_estimate": None,
        })
        if len(out) >= limit:
            break
    return out


def search_wikisource(query: str, language: str = "en", author: str = "", limit: int = 8) -> List[Dict[str, Any]]:
    """One request against `<lang>.wikisource.org` (en for 'any')."""
    lang = language if language and language != "any" else "en"
    srsearch = f"{query} {author}".strip()
    data = _get_json(f"https://{lang}.wikisource.org/w/api.php",
                     {"action": "query", "list": "search", "srsearch": srsearch, "srlimit": limit,
                      "srnamespace": 0, "format": "json"})
    out: List[Dict[str, Any]] = []
    for row in ((data or {}).get("query") or {}).get("search") or []:
        title = row.get("title") or ""
        m = re.search(r"\(([^()]+)\)\s*$", title)
        out.append({
            "title": title,
            "author": m.group(1) if m and not re.search(r"\d", m.group(1)) else "",
            "language": lang,
            "source": "wikisource",
            "url": f"https://{lang}.wikisource.org/wiki/{quote(title.replace(' ', '_'))}",
            "page": title,
            "wiki_lang": lang,
            "snippet": _strip_tags(row.get("snippet", "")),
            "tags": [],
            "death_year": None,
            "words_estimate": row.get("wordcount"),
        })
    return out


def search_archive(query: str, language: str = "any", author: str = "", limit: int = 8) -> List[Dict[str, Any]]:
    """One request to the Internet Archive's advanced search (texts only)."""
    q = f"({query}) AND mediatype:texts"
    names = [w for w in re.findall(r"[^\W\d_]+", author or "") if len(w) >= 3]
    if names:  # the Archive files creators as 'James, M. R. (Montague Rhodes), 1862-1936'
        q += " AND creator:(" + " AND ".join(names) + ")"
    code = ARCHIVE_LANG.get(language or "")
    if code:
        q += f" AND (language:{code} OR language:\"{code}\")"
    data = _get_json("https://archive.org/advancedsearch.php",
                     {"q": q, "fl[]": ["identifier", "title", "creator", "date", "language"],
                      "rows": limit, "output": "json"})
    out: List[Dict[str, Any]] = []
    for doc in ((data or {}).get("response") or {}).get("docs") or []:
        ident = doc.get("identifier") or ""
        if not ident:
            continue
        creator = doc.get("creator") or ""
        if isinstance(creator, list):
            creator = creator[0] if creator else ""
        langs = doc.get("language") or ""
        if isinstance(langs, list):
            langs = langs[0] if langs else ""
        title = doc.get("title") or ident
        if isinstance(title, list):
            title = title[0]
        out.append({
            "title": str(title),
            "author": flip_name(str(creator)),
            "language": language if language != "any" else str(langs)[:3],
            "source": "archive",
            "url": f"https://archive.org/details/{ident}",
            "identifier": ident,
            "snippet": " ".join(x for x in (str(creator), str(doc.get("date") or "")[:10]) if x),
            "tags": [],
            "death_year": None,
            "words_estimate": None,
        })
    return out


def search_web(query: str, language: str = "any", author: str = "", limit: int = 8) -> List[Dict[str, Any]]:
    """The Studio's own web search (SearXNG / Wikipedia / DuckDuckGo)."""
    from app.services.web_research import web_research_service

    q = " ".join(x for x in (query, author, "story full text") if x)
    try:
        rows = web_research_service.search(q, max_results=limit) or []
    except Exception as exc:  # noqa: BLE001
        logger.info("story library: web search failed: %s", exc)
        rows = []
    out: List[Dict[str, Any]] = []
    for row in rows:
        url = row.get("url") or ""
        if not url.startswith(("http://", "https://")):
            continue
        out.append({
            "title": row.get("title") or url,
            "author": author,
            "language": language if language != "any" else "",
            "source": "web",
            "url": url,
            "snippet": (row.get("snippet") or "")[:400],
            "tags": [],
            "death_year": None,
            "words_estimate": None,
        })
    return out


_SEARCHERS = {"gutenberg": "search_gutendex", "wikisource": "search_wikisource",
              "archive": "search_archive", "web": "search_web"}


def _url_key(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower()).rstrip("/")


def _score(c: Dict[str, Any], query: str, language: str, author: str) -> float:
    words = [w[:4] for w in _norm(query).split() if len(w) >= 3]
    hay = _norm(f"{c.get('title', '')} {c.get('snippet', '')} {' '.join(c.get('tags') or [])}")
    score = sum(2.0 for w in words if w in hay)
    if author and c.get("source") != "web":  # a web row's author is only the one asked for
        a_words = [w for w in _norm(author).split() if len(w) >= 3]
        if a_words and all(w in _norm(c.get("author", "")) for w in a_words):
            score += 3.0
    score += SOURCE_WEIGHT.get(c.get("source", ""), 0.0)
    status = (c.get("rights") or {}).get("status")
    score += 1.0 if status == "public_domain" else (-1.0 if status == "protected" else 0.0)
    if language and language != "any" and (c.get("language") or "").startswith(language):
        score += 1.0
    return score


def search(query: str, *, language: str = "any", author: str = "", source: str = "any", limit: int = 8,
           progress: ProgressFn = None) -> List[Dict[str, Any]]:
    """Candidates from every source (or one), merged, deduped by url and by
    title + author, rights guessed without the network, best first."""
    query = (query or "").strip()
    author = (author or "").strip()
    language = (language or "any").strip().lower() or "any"
    if not query and not author:
        raise ValueError("A query or an author is needed")
    limit = max(1, min(int(limit or 8), 30))
    chosen = SOURCES if source in ("", "any", None) else (source,)
    unknown = [s for s in chosen if s not in _SEARCHERS]
    if unknown:
        raise ValueError(f"Unknown source {unknown[0]!r}: one of {', '.join(SOURCES)} or any")
    found: List[Dict[str, Any]] = []
    for name in chosen:
        _say(progress, f"Searching {name}")
        fn = globals()[_SEARCHERS[name]]
        try:
            rows = fn(query or author, language=language, author=author, limit=limit) or []
        except Exception as exc:  # noqa: BLE001 - one source down never fails the search
            logger.info("story library: %s search failed: %s", name, exc)
            rows = []
        found.extend(rows)
    seen_urls, seen_works, merged = set(), set(), []
    for c in sorted(found, key=lambda r: -SOURCE_WEIGHT.get(r.get("source", ""), 0.0)):
        u = _url_key(c.get("url", ""))
        work = (_norm(c.get("title", "")), _norm(c.get("author", "")))
        if not u or u in seen_urls or (work[1] and work in seen_works):
            continue
        seen_urls.add(u)
        seen_works.add(work)
        c["rights"] = quick_rights(c.get("author", ""), c.get("death_year"), c.get("source", ""))
        merged.append(c)
    merged.sort(key=lambda c: -_score(c, query, language, author))
    _say(progress, f"{len(merged[:limit])} candidates")
    return merged[:limit]


# ──────────────────────────── fetching ────────────────────────────

def _gutenberg_id(c: Dict[str, Any]) -> str:
    m = re.search(r"/(?:ebooks|files|epub)/(\d+)", c.get("url", "") + " " + c.get("text_url", ""))
    return m.group(1) if m else ""


def fetch_gutenberg_text(c: Dict[str, Any]) -> str:
    """At most three tries: the catalogue's text/plain url, then the two usual paths."""
    gid = _gutenberg_id(c)
    urls = [c.get("text_url") or ""]
    if gid:
        urls += [f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt",
                 f"https://www.gutenberg.org/files/{gid}/{gid}-0.txt"]
    for url in [u for u in urls if u][:3]:
        text = _get_text(url)
        if text.strip():
            return strip_gutenberg(text)
    return ""


def fetch_wikisource_text(c: Dict[str, Any]) -> Dict[str, str]:
    """One request: the rendered page (transcluded scans included) plus the
    wikitext for the header's author."""
    lang = c.get("wiki_lang") or (c.get("language") if c.get("language") not in ("", "any", None) else "en")
    page = c.get("page") or ""
    if not page:
        m = re.search(r"/wiki/(.+)$", c.get("url", ""))
        page = requests.utils.unquote(m.group(1)).replace("_", " ") if m else ""
    if not page:
        return {"text": "", "author": ""}
    data = _get_json(f"https://{lang}.wikisource.org/w/api.php",
                     {"action": "parse", "page": page, "prop": "text|wikitext", "redirects": 1,
                      "formatversion": 2, "format": "json"})
    parsed = (data or {}).get("parse") or {}
    wikitext = parsed.get("wikitext") or ""
    text = html_to_text(parsed.get("text") or "")
    if count_words(text) < MIN_WORDS and wikitext:
        text = wikitext_to_text(wikitext)
    return {"text": text, "author": _wikisource_author(wikitext)}


def fetch_archive_text(c: Dict[str, Any]) -> str:
    ident = c.get("identifier") or ""
    if not ident:
        m = re.search(r"archive\.org/(?:details|download)/([^/?#]+)", c.get("url", ""))
        ident = m.group(1) if m else ""
    if not ident:
        return ""
    return _get_text(f"https://archive.org/download/{ident}/{ident}_djvu.txt").replace("\r\n", "\n")


def fetch_web_text(c: Dict[str, Any]) -> str:
    from app.services.web_research import web_research_service

    text = web_research_service.fetch(c.get("url", ""), max_chars=2_000_000) or ""
    if text.startswith(("Error:", "Could not fetch", "No extractable")):
        return ""
    return text


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:40].strip("-")


def _make_id(c: Dict[str, Any]) -> str:
    digest = hashlib.sha1(_url_key(c.get("url", "")).encode("utf-8")).hexdigest()[:8]
    base = "-".join(x for x in (_slug(c.get("author", "")), _slug(c.get("title", ""))) if x) or "story"
    return f"{base[:60].strip('-')}-{digest}"


def _first_lines(text: str, n: int = 5) -> str:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    return "\n".join(lines[:n])[:600]


def _summary(c: Dict[str, Any], text: str) -> str:
    snippet = (c.get("snippet") or "").strip()
    if len(snippet) >= 60 and c.get("source") in ("wikisource", "web"):
        return snippet[:400]
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if count_words(p) >= 25]
    lead = re.sub(r"\s+", " ", paras[0]) if paras else re.sub(r"\s+", " ", text[:400])
    return lead[:400]


def _index_row(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {k: meta.get(k) for k in ("id", "title", "author", "language", "source", "source_url",
                                     "fetched_at", "words")} | {"rights": (meta.get("rights") or {}).get("status")}


def fetch(candidate: Dict[str, Any], progress: ProgressFn = None) -> Dict[str, Any]:
    """Fetch a candidate's full text, decide the rights and store it. Raises
    ValueError with a plain reason when the text cannot be had, is too short, or
    is over 60,000 words."""
    c = dict(candidate or {})
    src = c.get("source") or ""
    if src not in SOURCES:
        raise ValueError(f"Unknown source {src!r}")
    if not c.get("url"):
        raise ValueError("The candidate has no url")
    if src == "web" and re.search(r"gutenberg\.org/(ebooks|files|cache/epub)/\d+", c["url"]):
        src = c["source"] = "gutenberg"  # a web hit on a Gutenberg book: take the clean text
    _say(progress, f"Fetching from {src}")
    if src == "gutenberg":
        text = fetch_gutenberg_text(c)
    elif src == "wikisource":
        got = fetch_wikisource_text(c)
        text = got.get("text", "")
        if got.get("author") and not c.get("author"):
            c["author"] = got["author"]
    elif src == "archive":
        text = fetch_archive_text(c)
    else:
        text = fetch_web_text(c)
    text = (text or "").replace("\r\n", "\n").strip()
    words = count_words(text)
    if words < MIN_WORDS:
        raise ValueError(f"Could not get the text of '{c.get('title', '')}' from {src} "
                         f"({words} words came back)")
    if words > MAX_WORDS:
        raise ValueError(f"'{c.get('title', '')}' is {words:,} words; the library keeps a story of up to "
                         f"{MAX_WORDS:,} words. Pick a single story rather than the whole book.")
    _say(progress, "Checking the rights")
    author = flip_name(c.get("author", ""))
    rights = rights_for(author)
    if rights.get("status") == "unknown" and rights.get("source") != "known_protected" \
            and c.get("death_year") is not None:
        rights = quick_rights("", c.get("death_year"), src)
    lang = detect_language(text, c.get("language") or "")
    sid = _make_id(c)
    meta = {
        "id": sid,
        "title": c.get("title", ""),
        "author": author,
        "language": lang,
        "source": src,
        "source_url": c.get("url", ""),
        "fetched_at": _now(),
        "words": words,
        "rights": rights,
        "summary": _summary(c, text),
        "tags": list(dict.fromkeys([*(c.get("tags") or []), src, lang]))[:12],
        "first_lines": _first_lines(text),
    }
    folder = _lib() / sid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "story.txt").write_text(text, encoding="utf-8")
    _write(folder / "meta.json", meta)
    with _lock:
        index = [row for row in _read(_lib() / "index.json", []) if row.get("id") != sid]
        index.insert(0, _index_row(meta))
        _write(_lib() / "index.json", index)
    _say(progress, f"Stored {sid} ({words} words, {rights.get('status')})")
    return meta


# ──────────────────────────── the library ────────────────────────────

def _valid_id(story_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,120}", story_id or ""))


def entries() -> List[Dict[str, Any]]:
    return _read(_lib() / "index.json", [])


def entry(story_id: str) -> Optional[Dict[str, Any]]:
    """meta.json plus `text` (the whole story) and `path`; None if unknown."""
    if not _valid_id(story_id):
        return None
    folder = _lib() / story_id
    meta = _read(folder / "meta.json", None)
    if not meta:
        return None
    try:
        text = (folder / "story.txt").read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        text = ""
    return {**meta, "text": text, "path": str(folder / "story.txt")}


def delete(story_id: str) -> bool:
    if not _valid_id(story_id):
        return False
    folder = _lib() / story_id
    existed = folder.exists()
    if existed:
        shutil.rmtree(folder, ignore_errors=True)
    with _lock:
        index = _read(_lib() / "index.json", [])
        kept = [row for row in index if row.get("id") != story_id]
        if len(kept) != len(index):
            _write(_lib() / "index.json", kept)
            existed = True
    return existed


# ──────────────────────────── jobs ────────────────────────────

_jobs: Dict[str, Dict[str, Any]] = {}


def start_job(kind: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    from integrations import idle_offload

    job_id = uuid.uuid4().hex[:12]
    job = {"job_id": job_id, "kind": kind, "state": "running", "message": "Starting", "result": None,
           "error": None, "started_at": _now()}
    _jobs[job_id] = job

    def progress(msg: str) -> None:
        job["message"] = msg

    def go() -> None:
        try:
            with idle_offload.busy():
                job["result"] = fn(*args, progress=progress, **kwargs)
            job["state"] = "done"
            job["message"] = "Done"
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            logger.exception("story library %s job failed", kind)
            job.update(state="failed", error=str(exc)[:300], message=f"Failed: {str(exc)[:120]}")
        finally:
            job["finished_at"] = _now()
            idle_offload.offload_now(f"story library {kind} finished")

    threading.Thread(target=go, name=f"story-library-{kind}-{job_id}", daemon=True).start()
    return job


def job(job_id: str) -> Optional[Dict[str, Any]]:
    return _jobs.get(job_id)
