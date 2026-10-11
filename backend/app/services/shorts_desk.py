"""Shorts Desk: find, score and build ready-to-record 1-2 minute vertical
shorts for Life3Baje (Hindi poems, sher-o-shayari), Raat3Baje (horror
incidents) and Beyond3Baje (entities / anomalies).

Pipeline for one "find":
1. Live web search (the Studio's SearXNG, `ddgs` fallback) for the format +
   filters. Nothing is taken from a model's memory: for poems/shayari the
   scout only extracts poets and first lines that appear in the results,
   and the REAL texts are then fetched from Kavita Kosh; for stories the
   pool is the web + news results themselves.
2. ShortsScout picks the best items from that pool by id (it cannot name
   anything that was not found), and each pick is grounded -- the poem text
   and the poet's dates for an informational rights label, or the cited
   pages fetched as the writer's research notes.
3. Evidence in parallel: a keyless YouTube search for similar shorts (views,
   durations, near-duplicates).
4. ViralityJudge scores the whole batch in one call against that evidence.

"Build" turns a candidate into a normal Studio project on the `shorts_ready`
workflow: ShortsWriter writes the framing (poems keep their text verbatim)
or the full script, with teleprompter pacing cues; the project gets a script
asset, a caption/hashtags package and vertical-short video settings, so the
creator records, drops the video in, and Produce Video takes it from there.

The daily batch (config `shorts_daily_*`) runs a find per channel every
morning and builds the best few. Every task ends with an offload of all
models (the GPU policy in integrations/idle_offload.py).
"""

import json
import logging
import os
import re
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.shorts_desk")

STORE_DIR = os.path.join(KNOWLEDGE_DIR, "shorts_desk")
WORKFLOW = "shorts_ready"
RECITE_WPM = 95          # poems are recited slowly
NARRATE_WPM = 140        # stories are narrated
MAX_SECONDS = 120

# --- formats ------------------------------------------------------------------

_POEM_FILTERS = [
    {"key": "era", "label": "Era", "options": ["Any", "Bhakti (Kabir, Tulsi, Meera)", "Riti", "Chhayavad (Nirala, Prasad, Pant, Mahadevi)",
                                             "Pragativad (Nagarjun, Kedarnath Agarwal)", "Nayi Kavita (Agyeya, Muktibodh, Raghuvir Sahay)",
                                             "Modern (Dushyant Kumar, Dhoomil, Kunwar Narayan, Kedarnath Singh)",
                                             "Contemporary (living poets, new voices)"]},
    {"key": "poet", "label": "Poet (optional)", "free": True},
    {"key": "theme", "label": "Theme", "options": ["Any", "Life & purpose", "Love", "Separation (viraha)", "Hope & courage",
                                                 "Loneliness", "Nature", "Spiritual / devotion", "Time & death", "Motivation",
                                                 "Society & protest", "Childhood & home"]},
    {"key": "length", "label": "Length", "options": ["Short (4-8 lines)", "Medium (up to 14 lines)", "Long (up to 24 lines)"]},
]
_SHAYARI_FILTERS = [
    {"key": "era", "label": "Era", "options": ["Any", "Classical (Mir, Ghalib, Daagh, Zauq)", "Progressive (Faiz, Sahir, Kaifi, Majrooh)",
                                             "Modern (Nida Fazli, Bashir Badr, Jaun Elia, Ahmad Faraz)",
                                             "Contemporary (Rahat Indori, Munawwar Rana, new voices)"]},
    {"key": "poet", "label": "Shayar (optional)", "free": True},
    {"key": "form", "label": "Form", "options": ["Any", "Sher (couplets)", "Ghazal", "Nazm", "Rubai", "Doha"]},
    {"key": "theme", "label": "Theme", "options": ["Any", "Ishq", "Dard / heartbreak", "Zindagi / life", "Khuda / faith",
                                                 "Dosti", "Tanhai", "Umeed", "Waqt"]},
    {"key": "length", "label": "Length", "options": ["Short (4-8 lines)", "Medium (up to 14 lines)", "Long (up to 24 lines)"]},
]

_WORLD_REGION = {"key": "region", "label": "Region", "options": [
    "Any (outside India)", "Japan", "United States", "Latin America / Mexico", "Southeast Asia", "UK & Ireland",
    "Europe", "Slavic / Eastern Europe", "Africa", "Australia", "Middle East", "Canada", "China / Korea"]}

FORMATS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "Life3Baje": {
        "poem": {"label": "Hindi poem (kavita)", "kind": "poem", "filters": _POEM_FILTERS,
                 "yt_suffix": "kavita shorts", "genre": "general", "music_hint": "sad_violin / morning_raga_flute"},
        "shayari": {"label": "Sher-o-shayari", "kind": "poem", "filters": _SHAYARI_FILTERS,
                    "yt_suffix": "shayari shorts", "genre": "general", "music_hint": "sad_violin"},
    },
    "Raat3Baje": {
        # INDIA ONLY (prompts/channels/Raat3Baje.md).
        "horror_incident": {"label": "Alleged incident (India)", "kind": "story", "filters": [
            {"key": "region", "label": "Region / state (optional)", "free": True},
            {"key": "type", "label": "Type", "options": ["Any", "Haunted place", "Highway / travel", "Hostel / school",
                                                         "Village", "Possession", "Real news report", "Hospital"]},
        ], "queries": ["{type} {region} India alleged horror incident reported", "{region} {type_hi} सच्ची डरावनी घटना",
                       "{region} India haunted {type} true story"],
           "news": "{type} {region} India haunted ghost", "defaults": {"type": "haunted", "type_hi": "भूतिया"},
           "yt_suffix": "horror story shorts", "genre": "horror", "music_hint": "horror_dark"},
        "folklore_entity": {"label": "Regional folklore entity", "kind": "story", "filters": [
            {"key": "region", "label": "Region", "options": ["Any", "Maharashtra / Konkan", "Bengal", "Rajasthan",
                                                            "Uttarakhand / Himachal", "UP / Bihar", "Gujarat",
                                                            "Kerala / South India", "Northeast", "Punjab"]},
            {"key": "entity", "label": "Entity (optional)", "free": True},
        ], "queries": ["{entity} {region} obscure Indian folklore entity legend", "{region} लोककथा {entity} भूत प्रेत मान्यता",
                       "{region} regional ghost belief origin {entity} India"],
           "defaults": {"entity": "", "region": ""},
           "yt_suffix": "folklore shorts", "genre": "horror", "music_hint": "horror_dark"},
        "ghost_story": {"label": "Original ghost story (fiction)", "kind": "fiction", "filters": [
            {"key": "setting", "label": "Setting", "options": ["Any", "Village", "Haveli", "Highway", "Hostel", "Hospital",
                                                             "Railway station", "Forest", "City apartment"]},
            {"key": "inspiration", "label": "Folklore to draw on (optional)", "free": True},
        ], "queries": ["{setting} {inspiration} Indian ghost folklore belief", "{setting} {inspiration} भूत लोककथा मान्यता",
                       "{setting} India haunted legend {inspiration}"],
           "defaults": {"setting": "village", "inspiration": ""},
           "yt_suffix": "horror story shorts", "genre": "horror", "music_hint": "horror_dark"},
        "rules_horror": {"label": "Rules horror (fiction)", "kind": "fiction", "filters": [
            {"key": "setting", "label": "Setting", "options": ["Any", "Night shift", "Haveli", "Highway dhaba", "Hostel",
                                                             "Hospital", "Village well", "Old railway station", "Masaan"]},
        ], "queries": ["{setting} Indian superstition rules at night", "{setting} रात के नियम अंधविश्वास",
                       "rules horror story {setting} creepy rules"],
           "defaults": {"setting": "night shift"},
           "yt_suffix": "horror shorts", "genre": "horror", "music_hint": "horror_dark"},
    },
    "Beyond3Baje": {
        # OUTSIDE INDIA ONLY, one format per pillar (prompts/channels/Beyond3Baje.md).
        "entity": {"label": "Entity file", "kind": "story", "filters": [_WORLD_REGION],
                   "queries": ["{region} folklore entity legend origin", "{region} supernatural creature earliest references",
                               "{region} entity alleged encounters explanation"],
                   "defaults": {"region": "world"}, "yt_suffix": "legend shorts", "genre": "mystery", "music_hint": "suspense"},
        "encounter": {"label": "Encounter file", "kind": "story", "filters": [_WORLD_REGION],
                      "queries": ["{region} alleged paranormal encounter witnesses date", "{region} mass sighting unexplained witnesses",
                                  "{region} famous paranormal encounter documented"],
                      "news": "{region} paranormal sighting", "defaults": {"region": "world"},
                      "yt_suffix": "paranormal shorts", "genre": "mystery", "music_hint": "suspense"},
        "case_file": {"label": "Paranormal case file", "kind": "story", "filters": [_WORLD_REGION],
                      "queries": ["{region} famous paranormal case investigation", "{region} haunting case claims vs evidence",
                                  "{region} poltergeist possession case investigator archive"],
                      "defaults": {"region": "world"}, "yt_suffix": "paranormal shorts", "genre": "mystery", "music_hint": "suspense"},
        "haunted_location": {"label": "Haunted location", "kind": "story", "filters": [_WORLD_REGION],
                             "queries": ["{region} haunted place history origin incident", "{region} haunted hotel castle hospital investigation",
                                         "{region} haunted location witness accounts"],
                             "defaults": {"region": "world"}, "yt_suffix": "haunted shorts", "genre": "mystery", "music_hint": "suspense"},
        "urban_legend": {"label": "International urban legend", "kind": "story", "filters": [_WORLD_REGION],
                         "queries": ["{region} urban legend origin", "{region} urban legend folklore vs creepypasta",
                                     "{region} modern urban legend explained"],
                         "defaults": {"region": "world"}, "yt_suffix": "urban legend shorts", "genre": "mystery", "music_hint": "suspense"},
        "unsolved": {"label": "Unsolved / strange case", "kind": "story", "filters": [_WORLD_REGION],
                     "queries": ["{region} unsolved eerie mystery disappearance", "{region} strange unexplained historical mystery",
                                 "{region} vanished expedition ship mystery"],
                     "defaults": {"region": "world"}, "yt_suffix": "mystery shorts", "genre": "mystery", "music_hint": "suspense"},
    },
}

_LENGTH_LINES = {"Short": 8, "Medium": 14, "Long": 24}


def formats() -> Dict[str, Any]:
    return {ch: {k: {"label": v["label"], "kind": v["kind"], "filters": v["filters"]} for k, v in fmts.items()}
            for ch, fmts in FORMATS.items()}


def _fmt(channel: str, fmt: str) -> Dict[str, Any]:
    try:
        return FORMATS[channel][fmt]
    except KeyError:
        raise ValueError(f"Unknown shorts format {channel}/{fmt}")


# --- storage ------------------------------------------------------------------

_lock = threading.Lock()


def _path(name: str) -> str:
    return os.path.join(STORE_DIR, name)


def _read(name: str, default: Any) -> Any:
    try:
        with open(_path(name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write(name: str, value: Any) -> None:
    with _lock:
        os.makedirs(STORE_DIR, exist_ok=True)
        tmp = _path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path(name))


def _used_titles(channel: str) -> List[str]:
    return list(_read("used.json", {}).get(channel, []))[-80:]


def _mark_used(channel: str, title: str) -> None:
    used = _read("used.json", {})
    used.setdefault(channel, []).append(title)
    used[channel] = used[channel][-300:]
    _write("used.json", used)


# --- model calls ------------------------------------------------------------------

_HASHTAG_ITEM_RE = re.compile(r'(?<=[\[,])(\s*)(#[^\s,\]"]+)')
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _fix_common_json(text: str) -> str:
    """The slips local models make in JSON: unquoted #hashtags in a list,
    trailing commas."""
    text = _HASHTAG_ITEM_RE.sub(r'\1"\2"', text)
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _parse_json(raw: Any) -> Optional[Dict[str, Any]]:
    from integrations.llm import clean_json_response
    text = clean_json_response(str(raw or ""))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    for candidate in (text, _fix_common_json(text)):
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else None
        except Exception:
            pass
    try:
        import json_repair
        data = json_repair.loads(_fix_common_json(text))
        return data if isinstance(data, dict) and data else None
    except Exception:
        return None


def _clean_text(value: Any) -> Any:
    """Drop lone surrogates (half an emoji) that a model sometimes emits: they
    crash every UTF-8 write downstream."""
    if isinstance(value, str):
        return value.encode("utf-8", "ignore").decode("utf-8")
    if isinstance(value, list):
        return [_clean_text(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean_text(v) for k, v in value.items()}
    return value


def _agent_json(agent: str, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One structured agent call. `purpose="production"` keeps local thinking
    models from reasoning at length: these are short JSON picks, and thinking
    made one call take ~90 s instead of ~15. Invalid JSON is repaired when it
    can be, else asked for once more with the parse error."""
    from core.agent import AgentFactory
    from integrations.llm import LLMService
    llm = LLMService(purpose="production")
    payload = task
    for attempt in range(2):
        try:
            raw = AgentFactory.get_agent(agent, llm).execute(json.dumps(payload, ensure_ascii=False), require_json=True)
        except Exception as exc:
            logger.warning("%s call failed: %s", agent, str(exc)[:200])
            return None
        data = _parse_json(raw)
        if data is not None:
            return _clean_text(data)
        logger.warning("%s returned invalid JSON (attempt %d)", agent, attempt + 1)
        payload = {**task, "previous_answer_was_invalid_json":
                   "Your last answer could not be parsed. Reply again with ONLY one valid JSON object: "
                   "double-quoted strings (hashtags too), no trailing commas, no comments."}
    return None


# --- search vocabulary (query words only -- never content) ----------------------------

THEME_HI = {
    "Life & purpose": "ज़िन्दगी", "Love": "प्रेम", "Separation (viraha)": "विरह", "Hope & courage": "हौसला उम्मीद",
    "Loneliness": "अकेलापन", "Nature": "प्रकृति", "Spiritual / devotion": "भक्ति", "Time & death": "समय मृत्यु",
    "Motivation": "प्रेरणा", "Society & protest": "समाज", "Childhood & home": "बचपन", "Ishq": "इश्क़",
    "Dard / heartbreak": "दर्द", "Zindagi / life": "ज़िन्दगी", "Khuda / faith": "ख़ुदा", "Dosti": "दोस्ती",
    "Tanhai": "तन्हाई", "Umeed": "उम्मीद", "Waqt": "वक़्त",
}
ERA_HI = {"Bhakti": "भक्तिकाल", "Riti": "रीतिकाल", "Chhayavad": "छायावाद", "Pragativad": "प्रगतिवाद",
          "Nayi": "नई कविता", "Modern": "आधुनिक हिंदी कविता", "Contemporary": "समकालीन हिंदी कविता नए कवि"}
ERA_SHAYARI_HI = {"Classical": "क्लासिकी उर्दू शायरी", "Progressive": "तरक़्क़ी-पसंद शायरी",
                  "Modern": "जदीद आधुनिक शायरी", "Contemporary": "समकालीन शायरी नए शायर"}
FORM_HI = {"Sher": "शेर", "Ghazal": "ग़ज़ल", "Nazm": "नज़्म", "Rubai": "रुबाई", "Doha": "दोहे"}
_UNREADABLE = ("youtube.com", "youtu.be", "instagram.com", "facebook.com", "pinterest.", "x.com", "twitter.com",
               "dailymotion.com", "tiktok.com", "reddit.com/gallery", "spotify.com", "jiosaavn.com")
MIN_SOURCE_CHARS = 600   # a "source" shorter than this is a stub, not research


def _first_word(value: str) -> str:
    return (value or "").split(" ")[0].split("(")[0].strip()


def _web(queries: List[str], per_query: int = 8, news_query: Optional[str] = None) -> List[Dict[str, str]]:
    """Live web results for several queries in parallel, de-duplicated."""
    from app.services.web_research import search_news, search_web
    jobs = [(q, False) for q in queries if q] + ([(news_query, True)] if news_query else [])
    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(lambda job: search_news(job[0], per_query) if job[1]
                                else search_web(job[0], max_results=per_query), jobs))
    seen, out = set(), []
    for batch in batches:
        for r in batch:
            url = r.get("url") or ""
            if url and url not in seen:
                seen.add(url)
                out.append({"title": r.get("title", ""), "snippet": (r.get("snippet") or "")[:300], "url": url,
                            "source": r.get("source", "")})
    return out


# --- poems: web search -> Kavita Kosh -> real text ------------------------------------

def _kk_title_from_url(url: str) -> Optional[str]:
    from urllib.parse import unquote
    m = re.search(r"kavitakosh\.org/kk/([^?#]+)", url or "")
    if not m:
        return None
    title = unquote(m.group(1)).replace("_", " ")
    return title if " / " in title else None


def _poet_works(poet: str, limit: int) -> List[str]:
    """Real poem page titles linked from a poet's (or collection) page."""
    import random
    import requests
    from app.services import poetry_sources as ps
    hits = [h for h in ps.search_kavitakosh(poet, limit=5) if not h.get("poet")]
    page = hits[0]["title"] if hits else poet
    try:
        data = requests.get(ps.KAVITAKOSH_API, params={"action": "parse", "page": page, "prop": "links",
                                                       "format": "json", "redirects": 1},
                            headers=ps.HEADERS, timeout=ps.TIMEOUT).json()
    except Exception:
        return []
    links = [l.get("*", "") for l in (data.get("parse") or {}).get("links") or []]
    works = [t for t in links if " / " in t]
    random.shuffle(works)
    return works[:limit]


def _poem_pool(fmt_key: str, filters: Dict[str, str], say) -> List[Dict[str, Any]]:
    from app.services import poetry_sources as ps
    poet = filters.get("poet", "").strip()
    theme = filters.get("theme", "")
    theme_hi = THEME_HI.get(theme, "")
    era_key = _first_word(filters.get("era", ""))
    era_hi = (ERA_SHAYARI_HI if fmt_key == "shayari" else ERA_HI).get(era_key, "")
    form_hi = FORM_HI.get(_first_word(filters.get("form", "")), "")
    kind_hi = form_hi or ("शायरी" if fmt_key == "shayari" else "कविता")
    kind_en = "shayari sher" if fmt_key == "shayari" else "hindi poem kavita"

    say("Searching the web")
    queries = [
        f"{poet or era_hi} {theme_hi} {kind_hi} kavitakosh".strip(),
        f"best {kind_en} {poet} {theme} {filters.get('era', '')}".strip(),
        f"{poet} {theme_hi} {kind_hi} प्रसिद्ध".strip(),
    ]
    if not poet and not era_key:
        # No era chosen: search modern and contemporary voices on purpose, so
        # the pool is not only the few classical names every list repeats.
        queries += [f"modern contemporary {kind_en} {theme} poets".strip(),
                    f"{'नए शायर' if fmt_key == 'shayari' else 'समकालीन कवि'} {theme_hi} {kind_hi}".strip()]
    web = _web(queries, per_query=8)

    titles: List[str] = [t for t in (_kk_title_from_url(r["url"]) for r in web) if t]
    named = re.search(r"\(([^)]*)\)", filters.get("era", ""))
    era_names = [n.strip() for n in (named.group(1).split(",") if named else [])]
    era_names = [n for n in era_names if n and not re.search(r"new voices|living|poets", n, re.I)]
    say("Reading the results")
    plan = _agent_json("ShortsScout", {
        # Kavita Kosh indexes poets in Devanagari: the scout returns these too.
        "poets_to_include": era_names,
        "task": "plan", "format": fmt_key, "filters": filters,
        "era_mix": ("Only the chosen era." if era_key else
                    "Mix eras: include modern and contemporary poets from the results, not only classical ones."),
        # Kept small: Devanagari costs several tokens a word, and a local model's
        # 16k context overflowed on 24 full results.
        "web_results": [{"title": r["title"][:90], "snippet": r["snippet"][:180]} for r in web[:16]],
    }) or {}
    # Poets named in the era the creator picked ("Modern (Nida Fazli, Bashir
    # Badr, ...)") are the creator's own choice, so they seed the search too.
    poets = [p for p in ([poet] if poet else []) + list(plan.get("poets") or []) + era_names if p]
    poets = list(dict.fromkeys(poets))[:6]
    lines = [l for l in plan.get("lines") or [] if l][:10]

    say("Fetching poems from Kavita Kosh")
    with ThreadPoolExecutor(max_workers=8) as pool:
        for works in pool.map(lambda p: _poet_works(p, 10 if len(poets) > 1 else 24), poets):
            titles += works
        for hits in pool.map(lambda q: ps.search_kavitakosh(q, limit=3), lines):
            titles += [h["title"] for h in hits if h.get("poet")]
        if theme_hi:
            for hits in pool.map(lambda q: ps.search_kavitakosh(q, limit=8),
                                 [f"{theme_hi} {p}" for p in poets[:3]] or [f"{theme_hi} {kind_hi}"]):
                titles += [h["title"] for h in hits if h.get("poet")]
        seen, unique = set(), []
        for t in titles:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        poems = list(pool.map(ps.fetch_poem, unique[:40]))

    max_lines = _max_lines(filters)
    pool_items = []
    seen_first: set = set()
    for poem in poems:
        if not poem or poem["lines"] < 2:
            continue
        # A poet filter means that poet's own work, not poems that mention him.
        if poet and not (_loose(poet) in _loose(poem.get("poet", "")) or _loose(poem.get("poet", "")) in _loose(poet)):
            continue
        text = ps.excerpt(poem["text"], max_lines)
        seconds = round(_words(text) / RECITE_WPM * 60 + 6)
        if seconds > MAX_SECONDS + 20:
            text = ps.excerpt(poem["text"], max(4, max_lines // 2))
            seconds = round(_words(text) / RECITE_WPM * 60 + 6)
        # The same poem often lives on two pages under different titles.
        first = _loose(next((ln for ln in poem["text"].split("\n") if ln.strip()), ""))[:40]
        if first in seen_first:
            continue
        seen_first.add(first)
        pool_items.append({**poem, "text": text, "est_seconds": seconds,
                           "excerpted": text.count("\n") + 1 < poem["lines"]})
    return pool_items


def _ground_poem(item: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import poetry_sources as ps
    info = ps.poet_info(item.get("poet", ""))
    return {**item, "source_url": item.get("url"), "glosses": (item.get("glosses") or [])[:12],
            "rights": info.get("rights", "unknown"), "poet_died": info.get("died"),
            "public_domain_from": info.get("public_domain_from")}


# --- stories: web + news search -> fetched pages -------------------------------------

_TYPE_HI = {"Haunted place": "भूतिया जगह", "Highway / travel": "हाईवे", "Hostel / school": "हॉस्टल",
            "Village": "गाँव", "Possession": "आत्मा", "Real news report": "ख़बर", "Hospital": "अस्पताल"}


def _story_pool(fmt_key: str, fmt: Dict[str, Any], filters: Dict[str, str], say) -> List[Dict[str, Any]]:
    """Web + news results for a story/fiction format, from the format's own
    query templates (a pillar searches for its kind of material)."""
    fill = {"type": "", "region": "", "entity": "", "setting": "", "inspiration": "", "type_hi": ""}
    fill.update(fmt.get("defaults") or {})
    for key, value in filters.items():
        if value and not value.startswith("Any"):
            fill[key] = value
    if filters.get("type"):
        fill["type_hi"] = _TYPE_HI.get(filters["type"], fill["type_hi"])
    queries = [" ".join(q.format(**fill).split()) for q in fmt["queries"]]
    news = " ".join(fmt["news"].format(**fill).split()) if fmt.get("news") else None
    say("Searching the web and news")
    results = _web(queries, per_query=8, news_query=news)
    return [r for r in results if not any(host in r["url"] for host in _UNREADABLE)][:28]


def _fetch_note(r: Dict[str, str]) -> Optional[Dict[str, str]]:
    from app.services.web_research import fetch_page_content
    if any(host in r.get("url", "") for host in _UNREADABLE):
        return None
    try:
        body = fetch_page_content(r["url"], max_chars=2500) or ""
    except Exception:
        body = ""
    if len(body) < MIN_SOURCE_CHARS:
        return None
    return {"title": r.get("title", ""), "url": r["url"], "snippet": r.get("snippet", ""), "text": body[:2500]}


def _ground_story(cand: Dict[str, Any], by_id: Dict[str, Dict[str, Any]], fiction: bool = False) -> Dict[str, Any]:
    """Fetch the pages the scout cited: the writer works only from these. A
    pick whose cited pages are stubs gets one follow-up search on its title,
    so every story reaches the writer with real text behind it."""
    notes = [n for n in (_fetch_note(by_id[rid]) for rid in (cand.get("source_ids") or [])[:3] if rid in by_id) if n]
    if not notes:
        from app.services.web_research import search_web
        for r in search_web(cand.get("title", ""), max_results=6):
            note = _fetch_note(r)
            if note:
                notes.append(note)
            if len(notes) >= 2:
                break
    return {**cand, "notes": notes, "source_url": notes[0]["url"] if notes else "", "est_seconds": 90,
            "rights": "original fiction" if fiction else "original script",
            # Fiction only borrows atmosphere and beliefs: it may go ahead on thin sources.
            "thin_sources": not notes and not fiction}


def _guide(channel: str) -> str:
    """The channel guide's essentials (its first section) for every agent call:
    geography, pillars, integrity rules."""
    try:
        from app.services.studio_chat import channel_guide
        return channel_guide(channel)[:1500]
    except Exception:
        return ""


def _max_lines(filters: Dict[str, str]) -> int:
    length = (filters.get("length") or "Short").split(" ")[0]
    return _LENGTH_LINES.get(length, 8)


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def _loose(s: str) -> str:
    return re.sub(r"[\s'’‘\"\-]", "", s or "")


def _evidence(cand: Dict[str, Any], fmt: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.video_intel import search_youtube
    query = " ".join(x for x in (cand.get("title"), cand.get("poet"), fmt["yt_suffix"]) if x)
    rows = search_youtube(query, limit=12)
    shorts = [r for r in rows if r.get("duration") and r["duration"] <= 180 and r.get("view_count") is not None]
    views = [r["view_count"] for r in shorts]
    key = set(_loose(w) for w in (cand.get("title") or "").split() if len(w) > 2)
    dupes = sum(1 for r in rows if key and len(key & set(_loose(w) for w in r.get("title", "").split())) >= max(1, len(key) // 2))
    return {
        "query": query, "results": len(rows), "short_results": len(shorts),
        "median_short_views": int(statistics.median(views)) if views else None,
        "max_short_views": max(views) if views else None,
        "near_duplicates": dupes,
        "top": [{"title": r["title"][:80], "views": r.get("view_count"), "seconds": r.get("duration")}
                for r in sorted(rows, key=lambda r: -(r.get("view_count") or 0))[:4]],
    }


# --- find -------------------------------------------------------------------------

def find(channel: str, fmt_key: str, filters: Optional[Dict[str, str]] = None, count: int = 6,
         progress=None) -> Dict[str, Any]:
    """Search -> pool of real material -> scout picks from it -> ground ->
    evidence -> judge. Nothing is taken from a model's memory."""
    fmt = _fmt(channel, fmt_key)
    filters = {k: v for k, v in (filters or {}).items() if v and v != "Any"}
    say = progress or (lambda msg: None)
    t0 = time.time()
    is_poem = fmt["kind"] == "poem"
    avoid = set(_used_titles(channel))

    pool_items = _poem_pool(fmt_key, filters, say) if is_poem else _story_pool(fmt_key, fmt, filters, say)
    pool_items = [p for p in pool_items if p.get("title") not in avoid]
    if not pool_items:
        return {"channel": channel, "format": fmt_key, "filters": filters, "candidates": [],
                "error": "The web search found nothing usable for these filters.", "seconds": round(time.time() - t0)}
    prefix = "p" if is_poem else "r"
    by_id = {f"{prefix}{i + 1}": item for i, item in enumerate(pool_items)}

    say(f"Choosing the best of {len(pool_items)} found")
    pick = _agent_json("ShortsScout", {
        "task": "select", "channel": channel, "format": fmt["label"], "kind": fmt["kind"], "filters": filters,
        "channel_guide": _guide(channel),
        "count": count + 2, "avoid_titles": sorted(avoid)[:30],
        # Opening lines only (and short snippets): the whole pool has to fit a
        # local model's context alongside the persona.
        "pool": [({"id": k, "title": v["title"][:80], "poet": v.get("poet", ""),
                   "opening": " / ".join([ln for ln in v["text"].split("\n") if ln.strip()][:3])[:220],
                   "est_seconds": v.get("est_seconds")} if is_poem else
                  {"id": k, "title": v["title"][:90], "snippet": v["snippet"][:200]})
                 for k, v in list(by_id.items())[:24]],
    }) or {}
    chosen = [c for c in pick.get("candidates") or [] if isinstance(c, dict) and c.get("id") in by_id]
    if not chosen:
        # No usable pick: fall back to the pool order rather than nothing.
        chosen = [{"id": k} for k in list(by_id)[: count + 2]]

    say("Grounding and checking YouTube Shorts")
    with ThreadPoolExecutor(max_workers=8) as pool:
        if is_poem:
            grounded = list(pool.map(lambda c: _ground_poem({
                **by_id[c["id"]],
                **{k: v for k, v in c.items() if k not in ("id", "title") and v},
                "working_title": c.get("title", "")}), chosen))
        else:
            fiction = fmt["kind"] == "fiction"
            grounded = list(pool.map(lambda c: _ground_story({**c, "title": c.get("title") or by_id[c["id"]]["title"],
                                                               "source_ids": c.get("source_ids") or [c["id"]]}, by_id,
                                                              fiction), chosen))
        grounded = [g for g in grounded if not g.get("thin_sources")]
        seen, unique = set(), []
        for g in grounded:
            key = g.get("source_url") or g["title"]
            if key not in seen:
                seen.add(key)
                unique.append(g)
        grounded = unique[: count + 2]
        evidence = list(pool.map(lambda g: _evidence(g, fmt), grounded))
    for i, (g, ev) in enumerate(zip(grounded, evidence)):
        g["id"] = f"c{i + 1}"
        g["evidence"] = ev
    dropped = 0

    if grounded:
        say("Scoring for virality and quality")
        judged = _agent_json("ViralityJudge", {
            "channel": channel, "format": fmt["label"], "channel_guide": _guide(channel)[:900],
            "candidates": [{"id": g["id"], "title": g["title"], "poet": g.get("poet", ""), "hook": g.get("hook", ""),
                            "angle": g.get("angle", ""), "opening": (g.get("text") or g.get("snippet") or "")[:160],
                            "est_seconds": g.get("est_seconds"),
                            "evidence": {**{k: v for k, v in g["evidence"].items() if k not in ("top", "query")},
                                         "top": g["evidence"]["top"][:2]}} for g in grounded],
        }) or {}
        scores = {s.get("id"): s for s in judged.get("scores") or [] if isinstance(s, dict)}
        for g in grounded:
            s = scores.get(g["id"]) or {}
            g["score"] = int(s.get("score") or 0)
            g["verdict"] = s.get("verdict") or ("unscored" if not scores else "maybe")
            g["reasons"] = s.get("reasons") or []
            g["best_title"] = s.get("best_title") or g["title"]
            g["angle_tip"] = s.get("angle_tip") or ""
            g["subscores"] = {k: s.get(k) for k in ("hook", "payoff", "demand", "fit", "freshness")}
        grounded.sort(key=lambda g: -g.get("score", 0))

    result = {
        "channel": channel, "format": fmt_key, "filters": filters, "candidates": grounded[:count],
        "dropped_unverified": dropped, "seconds": round(time.time() - t0),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    finds = _read("finds.json", [])
    finds.insert(0, result)
    _write("finds.json", finds[:30])
    return result


# --- build ------------------------------------------------------------------------

def _stanza_cues(text: str) -> str:
    """Poem text verbatim, with a pause between stanzas for the teleprompter."""
    stanzas = [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]
    return "\n\n(pause)\n\n".join(stanzas)


def _ascii_slug(text: str, fallback: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    return " ".join(words[:8]) or fallback


def _creator_style(channel: str) -> Optional[str]:
    try:
        from app.services import writing_style
        return writing_style.style_section(channel).strip()[:5000] or None
    except Exception:  # noqa: BLE001 - a Short is written without it
        return None


def build(channel: str, fmt_key: str, cand: Dict[str, Any]) -> Dict[str, Any]:
    """Write the package and create the project. Returns the project dict."""
    from core.models.project import Project, StepExecution
    from executive.project import project_manager

    fmt = _fmt(channel, fmt_key)
    is_poem = fmt["kind"] == "poem"
    pkg = _agent_json("ShortsWriter", {
        "channel": channel, "format": fmt["label"], "kind": fmt["kind"], "format_key": fmt_key,
        "channel_guide": _guide(channel),
        # How the creator himself writes and talks (app/services/writing_style.py):
        # the framing he will say must sound like him. Poem text stays verbatim.
        "creator_writing_style": _creator_style(channel),
        "candidate": {k: cand.get(k) for k in ("title", "best_title", "poet", "hook", "angle", "angle_tip",
                                               "theme", "era", "kind", "reasons")},
        "poem_text_inserted_verbatim": cand.get("text") if is_poem else None,
        "word_meanings": cand.get("glosses") if is_poem else None,
        "research_notes": cand.get("notes") if not is_poem else None,
    }) or {}

    title = pkg.get("title") or cand.get("best_title") or cand.get("title")
    if is_poem:
        parts = [f"# {title}", ""]
        if pkg.get("intro"):
            parts += [f"(slow) {pkg['intro']} (pause)", ""]
        parts += [_stanza_cues(cand.get("text") or ""), ""]
        if pkg.get("outro"):
            parts += [f"(pause) {pkg['outro']}"]
        parts += ["", f"— {cand.get('poet', '')}"]
        script = "\n".join(parts).strip() + "\n"
    else:
        body = (pkg.get("script") or "").strip()
        if not body:
            raise RuntimeError("The writer returned no script.")
        script = f"# {title}\n\n{body}\n"

    working = _ascii_slug(pkg.get("title_en") or cand.get("search_query") or "", f"{fmt_key} {uuid.uuid4().hex[:4]}")
    project = None
    for attempt in range(5):
        try:
            project = project_manager.create_project(
                name=f"Short {working}" + (f" {attempt + 1}" if attempt else ""), brand=channel, workflow_name=WORKFLOW)
            break
        except ValueError:
            continue
    if project is None:
        raise RuntimeError("Could not create a unique project id.")

    pdir = project.get_project_dir()
    with open(os.path.join(pdir, "script", "short_script.md"), "w", encoding="utf-8") as f:
        f.write(script)
    package = {
        "title": title, "hook_line": pkg.get("hook_line", ""), "caption": pkg.get("caption", ""),
        "hashtags": pkg.get("hashtags") or [], "on_screen_text": pkg.get("on_screen_text", ""),
        "meaning_note": pkg.get("meaning_note", ""), "estimated_seconds": pkg.get("estimated_seconds") or cand.get("est_seconds"),
        "poet": cand.get("poet", ""), "source_url": cand.get("source_url", ""),
        "rights": cand.get("rights", ""), "poet_died": cand.get("poet_died"),
        "score": cand.get("score"), "verdict": cand.get("verdict"), "reasons": cand.get("reasons", []),
        "evidence": cand.get("evidence", {}), "notes": cand.get("notes", []),
    }
    with open(os.path.join(pdir, "publish", "short_package.json"), "w", encoding="utf-8") as f:
        json.dump(package, f, ensure_ascii=False, indent=2)

    now = datetime.now().isoformat()
    project.name = title
    project.current_step = "Ready to record"
    project.assets["script"] = "script/short_script.md"
    project.assets["short_package"] = "publish/short_package.json"
    project.steps_history.append(StepExecution(
        step_name="Short Script", agent_name="ShortsWriter", status="completed", started_at=now,
        completed_at=now, output_files={"script": "script/short_script.md"},
        logs=[f"Built by the Shorts Desk ({fmt['label']}), score {cand.get('score')}"]))
    project.metadata.update({
        "short_format": fmt_key, "short_channel": channel, "orientation": "vertical",
        "target_duration_minutes": 2, "shorts_desk": {"score": cand.get("score"), "verdict": cand.get("verdict")},
        # Vertical 1-2 min short: no shorts cut out of it, brisk visuals.
        "video_settings": {"shorts_clips": 0, "shorts_full": False, "genre": fmt["genre"],
                           "density": "busy", "broll_seconds_min": 2.5, "broll_seconds_max": 4.0},
    })
    project.save()
    _mark_used(channel, cand.get("title") or title)
    try:
        from app.services.events import bus
        bus.publish("project_created", {"project_id": project.id, "name": project.name, "brand": channel,
                                        "workflow_name": WORKFLOW, "current_step": project.current_step})
    except Exception:
        pass
    return Project.load(project.id).to_dict()


# --- jobs (find/build run in the background; the UI polls) -------------------------

_jobs: Dict[str, Dict[str, Any]] = {}


def start_job(kind: str, fn, *args) -> Dict[str, Any]:
    from integrations import idle_offload
    job_id = uuid.uuid4().hex[:12]
    job = {"job_id": job_id, "kind": kind, "state": "running", "message": "Starting", "result": None,
           "error": None, "started_at": datetime.now().isoformat(timespec="seconds")}
    _jobs[job_id] = job

    def progress(msg: str) -> None:
        job["message"] = msg

    def run() -> None:
        try:
            with idle_offload.busy():
                job["result"] = fn(*args, progress=progress) if kind == "find" else fn(*args)
            job["state"] = "done"
            job["message"] = "Done"
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            logger.exception("shorts %s job failed", kind)
            job.update(state="failed", error=str(exc)[:300])
        finally:
            idle_offload.offload_now(f"shorts {kind} finished")

    threading.Thread(target=run, name=f"shorts-{kind}-{job_id}", daemon=True).start()
    return job


def job(job_id: str) -> Optional[Dict[str, Any]]:
    return _jobs.get(job_id)


def recent_finds() -> List[Dict[str, Any]]:
    return _read("finds.json", [])


# --- daily batch ------------------------------------------------------------------

def daily_settings() -> Dict[str, Any]:
    from integrations.llm import load_config
    cfg = load_config()
    return {
        "enabled": bool(cfg.get("shorts_daily_enabled", False)),
        "time": str(cfg.get("shorts_daily_time", "07:00")),
        "per_channel": int(cfg.get("shorts_daily_per_channel", 2)),
        "min_score": int(cfg.get("shorts_daily_min_score", 60)),
        "last_run": _read("daily.json", {}).get("last_run", ""),
    }


def run_daily(progress=None) -> Dict[str, Any]:
    """One find per channel (rotating its formats day by day), then build the
    best candidates that clear the minimum score."""
    settings = daily_settings()
    day = datetime.now().timetuple().tm_yday
    built, skipped = [], []
    for channel, fmts in FORMATS.items():
        keys = list(fmts)
        fmt_key = keys[day % len(keys)]
        try:
            found = find(channel, fmt_key, {}, count=max(3, settings["per_channel"] + 2), progress=progress)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"channel": channel, "reason": str(exc)[:200]})
            continue
        good = [c for c in found["candidates"] if c.get("score", 0) >= settings["min_score"]][: settings["per_channel"]]
        if not good:
            skipped.append({"channel": channel, "reason": f"nothing scored >= {settings['min_score']}"})
        for cand in good:
            try:
                proj = build(channel, fmt_key, cand)
                built.append({"channel": channel, "format": fmt_key, "project_id": proj["id"], "title": proj["name"],
                              "score": cand.get("score")})
            except Exception as exc:  # noqa: BLE001
                skipped.append({"channel": channel, "reason": f"build failed: {str(exc)[:160]}"})
    record = {"last_run": datetime.now().date().isoformat(), "ran_at": datetime.now().isoformat(timespec="seconds"),
              "built": built, "skipped": skipped}
    history = _read("daily.json", {}).get("history", [])
    record["history"] = ([{k: record[k] for k in ("ran_at", "built", "skipped")}] + history)[:30]
    _write("daily.json", record)
    return record


NIGHTLY_LOCK = os.path.join(KNOWLEDGE_DIR, "nightly", "running.lock")


def _daily_due(now: datetime) -> bool:
    """The in-app schedule. When the nightly run (nightly_run.py, woken by
    Windows) is enabled it owns the batch; this only fires as a late fallback
    -- 4 h after the nightly time with no run that day -- and never while the
    nightly process holds its lock, so the two can never run at once."""
    from integrations.llm import load_config
    s = daily_settings()
    if not s["enabled"] or s["last_run"] == now.date().isoformat():
        return False
    if os.path.exists(NIGHTLY_LOCK) and time.time() - os.path.getmtime(NIGHTLY_LOCK) < 4 * 3600:
        return False
    cfg = load_config()
    when = str(cfg.get("nightly_time", "03:00")) if cfg.get("nightly_enabled") else s["time"]
    try:
        hh, mm = (int(x) for x in when.split(":")[:2])
    except ValueError:
        hh, mm = 7, 0
    if cfg.get("nightly_enabled"):
        hh = hh + 4
        if hh >= 24:
            return False
    return (now.hour, now.minute) >= (hh, mm)


_scheduler: Optional[threading.Thread] = None


def start_scheduler() -> None:
    """Checks once a minute; runs the daily batch once per day after its time."""
    global _scheduler
    if _scheduler and _scheduler.is_alive():
        return

    def loop() -> None:
        while True:
            try:
                if _daily_due(datetime.now()) and not any(
                        j["kind"] == "daily" and j["state"] == "running" for j in _jobs.values()):
                    logger.info("Shorts Desk: starting the daily batch")
                    start_job("daily", run_daily)
            except Exception as exc:  # noqa: BLE001
                logger.warning("shorts scheduler tick failed: %s", exc)
            time.sleep(60)

    _scheduler = threading.Thread(target=loop, name="shorts-daily", daemon=True)
    _scheduler.start()
