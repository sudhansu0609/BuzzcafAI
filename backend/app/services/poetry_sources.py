"""Real Hindi/Urdu poem text for the Shorts Desk -- never recalled from a
model's memory, which misquotes shers and invents verses.

Sources (both MediaWiki, keyless):
- Kavita Kosh (kavitakosh.org): the large Hindi/Urdu poetry wiki. Pages are
  titled "<poem> / <poet>"; the text sits in <poem>...</poem> with <ref>
  glosses (word meanings), and a poet page's {{KKParichay}} template has the
  poet's birth and death dates.
- Hindi Wikisource: public-domain texts (Kabir, Rahim, Tulsidas...).

Rights are informational only (the creator chose no filter): in India a work
stays in copyright until 60 years after the author's death, counted from the
next 1 January -- so a poet who died in year D is public domain from D + 61.

Every network call is best-effort and cached; nothing here raises.
"""

import json
import logging
import os
import re
import threading
from datetime import date
from typing import Any, Dict, List, Optional

import requests

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.poetry_sources")

KAVITAKOSH_API = "https://kavitakosh.org/kk/api.php"
KAVITAKOSH_PAGE = "https://kavitakosh.org/kk/"
WIKISOURCE_API = "https://hi.wikisource.org/w/api.php"
HEADERS = {"User-Agent": "BuzzcafStudio/1.0 (personal poetry research; contact via app owner)"}
TIMEOUT = 20

CACHE_DIR = os.path.join(KNOWLEDGE_DIR, "poetry_cache")
_cache_lock = threading.Lock()

_POEM_RE = re.compile(r"<poem>(.*?)</poem>", re.S | re.I)
_REF_RE = re.compile(r"<ref[^>]*>(.*?)</ref>", re.S | re.I)
_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}", re.S)
_LINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_CATEGORY_RE = re.compile(r"\[\[Category:[^\]]*\]\]", re.I)
_YEAR_RE = re.compile(r"(1[0-9]{3}|20[0-9]{2})")


def _cache_path(kind: str, key: str) -> str:
    safe = re.sub(r"[^\w\-]+", "_", key)[:120]
    return os.path.join(CACHE_DIR, kind, f"{safe}.json")


def _cached(kind: str, key: str) -> Optional[Any]:
    try:
        with open(_cache_path(kind, key), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _store(kind: str, key: str, value: Any) -> None:
    path = _cache_path(kind, key)
    try:
        with _cache_lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, indent=1)
    except Exception as exc:
        logger.debug("poetry cache write failed: %s", exc)


def _api(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = requests.get(url, params={**params, "format": "json"}, headers=HEADERS, timeout=TIMEOUT)
        return resp.json() if resp.status_code == 200 else {}
    except Exception as exc:
        logger.info("poetry source %s failed: %s", url, str(exc)[:160])
        return {}


def search_kavitakosh(query: str, limit: int = 10) -> List[Dict[str, str]]:
    """Poem pages matching `query`: [{title, poem, poet}] (poet from the
    "<poem> / <poet>" title; entries without a poet are poet/collection pages)."""
    key = f"{query}|{limit}"
    hit = _cached("search", key)
    if hit is not None:
        return hit
    data = _api(KAVITAKOSH_API, {"action": "query", "list": "search", "srsearch": query,
                                 "srlimit": limit, "srwhat": "text"})
    out = []
    for row in (data.get("query") or {}).get("search") or []:
        title = row.get("title") or ""
        poem, _, poet = title.rpartition(" / ")
        out.append({"title": title, "poem": poem or title, "poet": poet})
    _store("search", key, out)
    return out


def _clean_poem(raw: str) -> Dict[str, Any]:
    glosses: List[str] = []

    def _gloss(match: "re.Match") -> str:
        glosses.append(_LINK_RE.sub(r"\1", match.group(1)).strip())
        return ""

    text = _REF_RE.sub(_gloss, raw)
    text = _LINK_RE.sub(r"\1", text)
    text = re.sub(r"'''?", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    # Compilation pages number their shers ("1.", "2)") -- not something to recite.
    lines = [re.sub(r"^\s*\d{1,3}\s*[.)]\s*", "", ln).rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return {"text": text, "glosses": [g for g in glosses if g]}


def fetch_poem(title: str) -> Optional[Dict[str, Any]]:
    """The poem on a Kavita Kosh page, or None when the page has no <poem>
    block (a poet or collection index page)."""
    hit = _cached("poem", title)
    if hit is not None:
        return hit or None
    data = _api(KAVITAKOSH_API, {"action": "parse", "page": title, "prop": "wikitext|categories",
                                 "redirects": 1})
    parse = data.get("parse") or {}
    wikitext = (parse.get("wikitext") or {}).get("*") or ""
    blocks = _POEM_RE.findall(wikitext)
    if not blocks:
        _store("poem", title, {})
        return None
    cleaned = _clean_poem("\n\n".join(blocks))
    real_title = parse.get("title") or title
    poem_name, _, poet = real_title.rpartition(" / ")
    poet_match = re.search(r"\|\s*रचनाकार\s*=\s*([^\n|}]+)", wikitext)
    result = {
        "source": "Kavita Kosh",
        "title": poem_name or real_title,
        "poet": (poet_match.group(1).strip() if poet_match else poet) or "",
        "text": cleaned["text"],
        "glosses": cleaned["glosses"],
        "categories": [c.get("*", "") for c in parse.get("categories") or []],
        "url": KAVITAKOSH_PAGE + requests.utils.quote(real_title.replace(" ", "_")),
        "lines": len([ln for ln in cleaned["text"].split("\n") if ln.strip()]),
    }
    _store("poem", title, result)
    return result


def poet_info(poet: str) -> Dict[str, Any]:
    """{name, born, died, public_domain_from, rights} from the poet's Kavita
    Kosh page. `rights` is "public_domain", "protected" or "unknown"."""
    poet = (poet or "").strip()
    if not poet:
        return {"name": "", "rights": "unknown"}
    hit = _cached("poet", poet)
    if hit is not None:
        return hit
    data = _api(KAVITAKOSH_API, {"action": "parse", "page": poet, "prop": "wikitext", "redirects": 1})
    wikitext = ((data.get("parse") or {}).get("wikitext") or {}).get("*") or ""

    def field(name: str) -> str:
        m = re.search(rf"\|\s*{name}\s*=\s*([^\n|}}]*)", wikitext)
        return m.group(1).strip() if m else ""

    born_y = _YEAR_RE.search(field("जन्म"))
    died_y = _YEAR_RE.search(field("मृत्यु") or field("निधन"))
    info: Dict[str, Any] = {
        "name": field("नाम") or poet,
        "born": int(born_y.group(1)) if born_y else None,
        "died": int(died_y.group(1)) if died_y else None,
    }
    if info["died"]:
        info["public_domain_from"] = info["died"] + 61
        info["rights"] = "public_domain" if date.today().year >= info["died"] + 61 else "protected"
    elif info["born"] and date.today().year - info["born"] > 150:
        info["rights"] = "public_domain"          # medieval poets: no death field, long gone
    elif wikitext:
        info["rights"] = "protected"              # a page but no death date: likely living
    else:
        info["rights"] = "unknown"
    _store("poet", poet, info)
    return info


def search_wikisource(query: str, limit: int = 5) -> List[Dict[str, str]]:
    """Hindi Wikisource pages (public-domain texts) for `query`."""
    data = _api(WIKISOURCE_API, {"action": "query", "list": "search", "srsearch": query, "srlimit": limit})
    return [{"title": r.get("title", ""),
             "url": "https://hi.wikisource.org/wiki/" + requests.utils.quote(r.get("title", "").replace(" ", "_"))}
            for r in (data.get("query") or {}).get("search") or []]


def excerpt(text: str, max_lines: int) -> str:
    """The first `max_lines` non-empty lines, stopping at a stanza break when
    one falls near the limit -- a short should end on a whole couplet."""
    out: List[str] = []
    count = 0
    for line in text.split("\n"):
        if not line.strip():
            if count >= max_lines - 1 and out:
                break
            out.append("")
            continue
        out.append(line)
        count += 1
        if count >= max_lines:
            break
    return "\n".join(out).strip()
