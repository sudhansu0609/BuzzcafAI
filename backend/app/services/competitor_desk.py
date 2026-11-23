"""
The Competitor Desk: which videos of the competitor channels went viral in a
time range (views against that channel's own normal), why they worked, and a
one-click idea for OUR OWN version in the Topic Vault. No API key and no video
download: yt-dlp lists the channels flat and reads one video's metadata and
auto-captions. Competitors are found by `discover` (niche searches + which channels get the
views) or added by hand; they live in `audience_desk.sources(brand)["competitors"]`.

Files: knowledge/competitors/<Brand>/scan.json, analyses/<timestamp>.json.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR
from app.services import audience_desk

logger = logging.getLogger(__name__)

COMPETITORS_DIR = Path(KNOWLEDGE_DIR) / "competitors"
MAX_ANALYZE = 8
CAPTION_SECONDS = 120


def _brand_dir(brand: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", brand or "General")
    return COMPETITORS_DIR / safe


# ──────────────────────────── discover ────────────────────────────

MIN_APPEARANCES = 2
RELEVANCE_CANDIDATES = 25


def _guide(brand: str) -> str:
    from core.paths import CHANNELS_DIR
    path = Path(CHANNELS_DIR) / f"{brand}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _answer(data: Any, keys: tuple) -> Dict[str, Any]:
    """The part of the analyst's JSON that holds `keys`. The persona wraps its
    answers in an envelope ({"status", "agent", "results": {"..._report": {...}}}),
    which hid "keep" and made every relevance check look empty (2026-10-29)."""
    if isinstance(data, dict):
        if any(k in data for k in keys):
            return data
        for v in data.values():
            found = _answer(v, keys)
            if found:
                return found
    elif isinstance(data, list):
        for v in data:
            found = _answer(v, keys)
            if found:
                return found
    return {}


def niche_queries(brand: str) -> List[str]:
    """The brand's own queries plus 6-8 the analyst writes once from the channel
    guide (cached; rewritten when the guide file is newer)."""
    from app.services.shorts_desk import _agent_json
    from core.paths import CHANNELS_DIR
    from integrations.llm import llm_job

    base = list(audience_desk.sources(brand)["queries"])
    cache = _brand_dir(brand) / "queries.json"
    guide_path = Path(CHANNELS_DIR) / f"{brand}.md"
    cached = audience_desk._read(cache, {})
    fresh = bool(cached.get("queries")) and cache.exists() and (
        not guide_path.exists() or os.path.getmtime(guide_path) <= os.path.getmtime(cache))
    extra = [str(q).strip() for q in cached.get("queries") or []] if fresh else []
    if not extra and _guide(brand):
        task = {"task": ("Write 8 YouTube search phrases (Hindi in Roman letters, Hinglish and English) that viewers of this "
                         "channel's niche really type to find videos like ours. Phrases only, no channel names."),
                "brand": brand, "channel_guide": _guide(brand)[:1500], "existing_queries": base,
                "answer_format": {"queries": ["phrase"]}}
        with llm_job("research"):
            data = _agent_json("CompetitorAnalyst", task)
        extra = [str(q).strip() for q in _answer(data, ("queries",)).get("queries") or [] if str(q).strip()][:8]
        if extra:
            audience_desk._write(cache, {"queries": extra, "written_at": datetime.now().isoformat(timespec="seconds")})
    seen = {q.lower() for q in base}
    return base + [q for q in extra if q.lower() not in seen]


def _search_flat(url: str, limit: int) -> List[Dict[str, Any]]:
    try:
        with audience_desk._ydl(extract_flat=True, playlistend=limit) as ydl:
            return audience_desk._flat_entries(ydl.extract_info(url, download=False))[:limit]
    except Exception as exc:
        logger.warning("competitors: search failed %s: %s", url[:80], str(exc)[:160])
        return []


def search_both_ways(query: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Flat results for a query by relevance and sorted by views."""
    from urllib.parse import quote_plus
    by_views = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=CAM%253D"
    return _search_flat(f"ytsearch{limit}:{query}", limit) + _search_flat(by_views, limit)


def _norm(x: str) -> str:
    return str(x or "").strip().rstrip("/").lower()


def _channel_keys(url: str, channel_id: str = "") -> set:
    keys = {_norm(url), _norm(channel_id)}
    m = re.search(r"/channel/(UC[\w-]+)", str(url or ""))
    if m:
        keys.add(m.group(1).lower())
    return {k for k in keys if k}


def aggregate(results: Dict[str, List[Dict[str, Any]]], skip: set) -> List[Dict[str, Any]]:
    """Per channel: distinct queries it appears in, hit views, sample titles.
    Ranked by appearances x log10(median views); `skip` = own/excluded keys."""
    chans: Dict[str, Dict[str, Any]] = {}
    for query, entries in results.items():
        for e in entries:
            cid = e.get("channel_id") or ""
            if not cid or _channel_keys("", cid) & skip:
                continue
            c = chans.setdefault(cid, {"channel_id": cid, "name": e.get("channel") or cid, "queries": set(),
                                       "videos": {}, "titles": []})
            c["queries"].add(query)
            if e.get("id") not in c["videos"]:
                c["videos"][e.get("id")] = int(e.get("views") or 0)
                if len(c["titles"]) < 5 and e.get("title"):
                    c["titles"].append(e["title"])
    out = []
    for c in chans.values():
        views = list(c["videos"].values())
        median = statistics.median(views) if views else 0
        out.append({"channel_id": c["channel_id"], "name": c["name"], "url": f"https://www.youtube.com/channel/{c['channel_id']}",
                    "appearances": len(c["queries"]), "hits": len(views), "total_views": sum(views),
                    "median_views": int(median), "titles": c["titles"],
                    "score": len(c["queries"]) * math.log10(max(median, 10))})
    out.sort(key=lambda r: r["score"], reverse=True)
    repeated = [r for r in out if r["appearances"] >= MIN_APPEARANCES]
    return repeated if len(repeated) >= 3 else out


def _short_num(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{round(n / 1e3)}k" if n >= 1e3 else str(n)


def _relevant(brand: str, cands: List[Dict[str, Any]]) -> Dict[str, str]:
    """channel_id -> reason for the candidates the analyst keeps; {} if no usable answer."""
    from app.services.shorts_desk import _agent_json
    from integrations.llm import llm_job

    # Candidates are numbered: a small model garbles 24-character channel ids, and
    # an answer that matched nothing used to save the unfiltered list (2026-10-29:
    # MrBeast, Zee TV and kids' cartoons as Beyond3Baje's competitors).
    task = {"task": ("Pick the channels that are real competitors of this brand: the same niche, format and language audience. "
                     "Drop compilations of other people's videos, general entertainment/TV networks, celebrities, and news, "
                     "music or kids channels unless the brand is one. Answer with the candidates' numbers."),
            "brand": brand, "channel_guide": _guide(brand)[:1500],
            "candidates": [{"n": i, "name": c["name"], "sample_titles": c["titles"],
                            "queries_matched": c["appearances"], "median_views": c["median_views"]}
                           for i, c in enumerate(cands, 1)],
            "answer_format": {"keep": [{"n": 1, "reason": "one short line"}]}}
    by_name = {c["name"].strip().lower(): c["channel_id"] for c in cands if c.get("name")}
    ids = {c["channel_id"] for c in cands}
    keep: Dict[str, str] = {}
    for _ in range(2):
        with llm_job("research"):
            data = _agent_json("CompetitorAnalyst", task)
        for k in _answer(data, ("keep",)).get("keep") or []:
            if not isinstance(k, dict):
                continue
            cid = None
            try:
                n = int(k.get("n"))
                cid = cands[n - 1]["channel_id"] if 1 <= n <= len(cands) else None
            except (TypeError, ValueError):
                pass
            cid = cid or (k.get("channel_id") if k.get("channel_id") in ids else None) \
                or by_name.get(str(k.get("name") or "").strip().lower())
            if cid:
                keep[cid] = str(k.get("reason") or "").strip()
        if keep:
            break
    return keep


def discover(brand: str, max_channels: int = 10, progress: Optional[Callable[[str], None]] = None) -> List[Dict[str, Any]]:
    """Find the brand's competitors from its niche searches and which channels get the views."""
    say = progress or (lambda m: None)
    src = audience_desk.sources(brand)
    skip: set = set()
    for x in list(src["own"]) + audience_desk._own_channel_ids(brand) + list(src["excluded"]):
        skip |= _channel_keys(x, x)
    say("Writing the niche searches")
    queries = niche_queries(brand)
    results: Dict[str, List[Dict[str, Any]]] = {}
    for i, q in enumerate(queries, 1):
        say(f"Searching {i}/{len(queries)}: {q}")
        results[q] = search_both_ways(q)
    ranked = aggregate(results, skip)
    if not ranked:
        raise RuntimeError("The searches found no channels (offline, or YouTube did not answer).")
    cands = ranked[:RELEVANCE_CANDIDATES]
    say(f"Checking {len(cands)} channels against the niche")
    keep = _relevant(brand, cands)
    if not keep:
        # Never save the raw most-viewed list: keep what the brand had and try again next time.
        raise RuntimeError("The relevance check gave no usable answer; the competitor list was left as it was.")
    chosen = [c for c in cands if c["channel_id"] in keep]
    rows = []
    for c in chosen[:max_channels]:
        stats = f"{c['hits']} hits, median {_short_num(c['median_views'])} views"
        why = keep.get(c["channel_id"]) or f"in {c['appearances']} niche searches"
        rows.append({"url": c["url"], "name": c["name"], "source": "auto", "channel_id": c["channel_id"],
                     "reason": f"{why} ({stats})"})
    manual = [r for r in src["competitors"] if r.get("source") != "auto"]
    have: set = set()
    for r in manual:
        have |= _channel_keys(r["url"], r.get("channel_id", ""))
    rows = [r for r in rows if not (_channel_keys(r["url"], r["channel_id"]) & have)]
    audience_desk.set_sources(brand, {"competitors": manual + rows})
    audience_desk._write(_brand_dir(brand) / "discovered.json",
                         {"last_discovered": datetime.now().isoformat(timespec="seconds")})
    say(f"{len(rows)} competitors found")
    return rows


def exclude(brand: str, channel: str) -> Dict[str, Any]:
    """Remove a competitor and remember it so discovery never brings it back."""
    src = audience_desk.sources(brand)
    want = _channel_keys(channel, channel)
    keep, gone = [], set(want)
    for r in src["competitors"]:
        keys = _channel_keys(r["url"], r.get("channel_id", ""))
        if keys & want:
            gone |= keys
        else:
            keep.append(r)
    audience_desk.set_sources(brand, {"competitors": keep, "excluded": src["excluded"] + sorted(gone)})
    return audience_desk.sources(brand)


# ──────────────────────────── scan ────────────────────────────

def _published(entry: Dict[str, Any]) -> Optional[datetime]:
    ts = entry.get("timestamp") or entry.get("release_timestamp")
    if ts:
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    day = str(entry.get("upload_date") or "")
    if re.fullmatch(r"\d{8}", day):
        return datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
    return None


def _list_channel(url: str, limit: int) -> List[Dict[str, Any]]:
    """A channel's /videos tab, flat; the approximate_date arg gives each entry a timestamp."""
    url = url.rstrip("/")
    if not url.endswith("/videos"):
        url += "/videos"
    try:
        with audience_desk._ydl(extract_flat=True, playlistend=limit,
                                extractor_args={"youtubetab": {"approximate_date": [""]}}) as ydl:
            info = ydl.extract_info(url, download=False) or {}
    except Exception as exc:
        logger.warning("competitors: could not list %s: %s", url, str(exc)[:160])
        return []
    out = []
    for e in (info.get("entries") or [])[:limit]:
        if isinstance(e, dict) and e.get("id"):
            out.append(e)
    return out


def rows_from_entries(entries: List[Dict[str, Any]], channel_name: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Scan rows for one channel; outlier = views / the channel's median views here."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for e in entries:
        when = _published(e)
        if not when:
            continue
        views = int(e.get("view_count") or 0)
        age = max(0, (now - when).days)
        rows.append({
            "id": e["id"], "title": e.get("title") or "",
            "channel": e.get("channel") or e.get("uploader") or channel_name,
            "views": views, "duration": int(e.get("duration") or 0),
            "published": when.date().isoformat(), "age_days": age,
            "views_per_day": round(views / max(age, 1), 1),
        })
    median = statistics.median([r["views"] for r in rows]) if rows else 0
    for r in rows:
        r["outlier"] = round(r["views"] / median, 1) if median else 0.0
    return rows


def scan(brand: str, per_channel: int = 60, progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    say = progress or (lambda m: None)
    comps = audience_desk.sources(brand)["competitors"]
    if not comps:
        say("No competitors yet: finding them first")
        comps = discover(brand, progress=say)
    if not comps:
        raise RuntimeError("No competitor channels found: add some on the Competitors tab.")
    rows: List[Dict[str, Any]] = []
    for i, c in enumerate(comps, 1):
        say(f"Reading {c.get('name') or c['url']} ({i}/{len(comps)})")
        rows += rows_from_entries(_list_channel(c["url"], per_channel), c.get("name") or "")
    data = {"brand": brand, "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "channels": len(comps), "videos": rows}
    audience_desk._write(_brand_dir(brand) / "scan.json", data)
    say(f"{len(rows)} videos from {len(comps)} channels")
    return {"fetched_at": data["fetched_at"], "videos": len(rows), "channels": len(comps)}


# ──────────────────────────── nightly ────────────────────────────

def _guide_brands() -> List[str]:
    from core.paths import CHANNELS_DIR
    return sorted(p.stem for p in Path(CHANNELS_DIR).glob("*.md"))


def settings() -> Dict[str, Any]:
    data = audience_desk._read(COMPETITORS_DIR / "settings.json", {})
    brands = data.get("brands")
    return {
        "enabled": bool(data.get("enabled", True)),            # nightly scan
        "rediscover_days": max(1, int(data.get("rediscover_days", 7))),
        "brands": [str(b) for b in brands] if isinstance(brands, list) and brands else _guide_brands(),
        "last_run": data.get("last_run", ""),
        "last": data.get("last"),
    }


def set_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    data = audience_desk._read(COMPETITORS_DIR / "settings.json", {})
    for key in ("enabled", "rediscover_days", "brands", "last_run", "last"):
        if key in patch and patch[key] is not None:
            data[key] = patch[key]
    audience_desk._write(COMPETITORS_DIR / "settings.json", data)
    return settings()


def _last_discovered(brand: str) -> Optional[datetime]:
    raw = audience_desk._read(_brand_dir(brand) / "discovered.json", {}).get("last_discovered")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


def run_all(progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """The nightly pass: rediscover a brand's competitors when it has none or the
    list is older than `rediscover_days`, then scan. One brand failing never stops the rest."""
    from app.services import master_control
    say = progress or (lambda m: None)
    conf = settings()
    done: List[str] = []
    discovered: List[str] = []
    failed: List[Dict[str, str]] = []
    for brand in conf["brands"]:
        master_control.wait_if_paused("competitors")
        try:
            last = _last_discovered(brand)
            stale = last is None or (datetime.now() - last).days >= conf["rediscover_days"]
            if stale or not audience_desk.sources(brand)["competitors"]:
                say(f"{brand}: finding competitors")
                discover(brand, progress=say)
                discovered.append(brand)
            say(f"{brand}: scanning")
            scan(brand, progress=say)
            done.append(brand)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Competitor pass failed for %s: %s", brand, exc)
            failed.append({"brand": brand, "error": str(exc)[:200]})
    record = {"done": done, "discovered": discovered, "failed": failed}
    set_settings({"last_run": datetime.now().date().isoformat(), "last": record})
    return record


def videos(brand: str, days: int = 30, min_outlier: float = 0, sort: str = "outlier") -> Dict[str, Any]:
    data = audience_desk._read(_brand_dir(brand) / "scan.json", {})
    key = sort if sort in ("outlier", "views_per_day", "views") else "outlier"
    rows = [r for r in data.get("videos") or []
            if r.get("age_days", 0) <= days and r.get("outlier", 0) >= min_outlier]
    rows.sort(key=lambda r: r.get(key, 0), reverse=True)
    return {"brand": brand, "fetched_at": data.get("fetched_at", ""), "days": days, "videos": rows}


# ──────────────────────────── analysis ────────────────────────────

def _caption_text(info: Dict[str, Any]) -> str:
    """The first ~2 minutes of the auto-captions (hi, else en) as plain text."""
    import requests

    auto = info.get("automatic_captions") or {}
    for lang in ("hi", "en"):
        tracks = auto.get(lang) or auto.get(f"{lang}-orig") or []
        pick = next((t for t in tracks if t.get("ext") == "json3"), None) or next((t for t in tracks if t.get("ext") == "vtt"), None)
        if not pick or not pick.get("url"):
            continue
        try:
            resp = requests.get(pick["url"], timeout=25)
            resp.raise_for_status()
            if pick["ext"] == "json3":
                words = []
                for ev in resp.json().get("events") or []:
                    if int(ev.get("tStartMs") or 0) > CAPTION_SECONDS * 1000:
                        break
                    words.append("".join(s.get("utf8", "") for s in ev.get("segs") or []))
                text = " ".join(words)
            else:
                lines = [ln for ln in resp.text.splitlines() if ln.strip() and "-->" not in ln and not ln.startswith(("WEBVTT", "Kind:", "Language:"))]
                text = " ".join(re.sub(r"<[^>]+>", "", ln) for ln in lines)[:2500]
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                return text[:2500]
        except Exception as exc:
            logger.warning("competitors: captions failed (%s): %s", lang, str(exc)[:120])
    return ""


def video_detail(video_id: str) -> Dict[str, Any]:
    with audience_desk._ydl() as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False) or {}
    return {
        "id": video_id, "title": info.get("title") or "", "channel": info.get("channel") or info.get("uploader") or "",
        "description": (info.get("description") or "")[:1500], "duration": int(info.get("duration") or 0),
        "tags": (info.get("tags") or [])[:20],
        "chapters": [c.get("title") for c in (info.get("chapters") or []) if isinstance(c, dict)][:15],
        "views": info.get("view_count"), "likes": info.get("like_count"), "comments": info.get("comment_count"),
        "opening_captions": _caption_text(info),
    }


def analyze(brand: str, video_ids: List[str], progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    from app.services.shorts_desk import _agent_json
    from integrations.llm import llm_job

    say = progress or (lambda m: None)
    ids = [v for v in dict.fromkeys(video_ids) if v][:MAX_ANALYZE]
    if not ids:
        raise RuntimeError("No videos selected.")
    scan_rows = {r["id"]: r for r in audience_desk._read(_brand_dir(brand) / "scan.json", {}).get("videos") or []}
    details = []
    for i, vid in enumerate(ids, 1):
        say(f"Reading video {i}/{len(ids)}")
        try:
            d = video_detail(vid)
        except Exception as exc:
            logger.warning("competitors: could not read %s: %s", vid, str(exc)[:160])
            continue
        row = scan_rows.get(vid) or {}
        d.update(outlier=row.get("outlier"), views_per_day=row.get("views_per_day"), published=row.get("published"))
        details.append(d)
    if not details:
        raise RuntimeError("None of the selected videos could be read.")
    say("Analysing why they worked")
    task = {
        "task": ("These videos of competitor channels went viral (outlier = views against their channel's normal). "
                 "Learn what made each one work and make OUR OWN version: a new angle, our own research/story and words. "
                 "Never reuse their script lines, footage, thumbnail art or exact title (copyright and YouTube's reused-content rule)."),
        "brand": brand,
        "channel_is": audience_desk.NICHE.get(brand, "a Hindi storytelling channel"),
        "videos": details,
        "answer_format": {
            "videos": [{"id": "", "why_it_worked": "", "topic": "", "title_formula": "", "hook": "", "thumbnail_idea": "",
                        "length_note": "", "emotion": "", "audience": ""}],
            "patterns": ["what the winners share"],
            "title_formulas": ["reusable title shapes, with placeholders"],
            "gaps": ["what the viewers want that these videos do not give"],
            "ideas": [{"title": "our own title, not theirs", "angle": "the new angle", "why_it_could_work": "",
                       "format": "long | short | reel", "inspired_by": ["video ids"]}],
        },
        "rules": ["Answer with the JSON object only.", "Ideas must be original; inspired_by lists the ids that inspired them."],
    }
    with llm_job("research"):
        data = _answer(_agent_json("CompetitorAnalyst", task), ("videos", "patterns", "ideas"))
    if not data:
        raise RuntimeError("The analyst did not return a usable answer.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    result = {"brand": brand, "analysed_at": datetime.now().isoformat(timespec="seconds"),
              "video_ids": [d["id"] for d in details], "sources": [
                  {k: d.get(k) for k in ("id", "title", "channel", "views", "outlier", "views_per_day")} for d in details],
              **{k: data.get(k) or [] for k in ("videos", "patterns", "title_formulas", "gaps", "ideas")}}
    audience_desk._write(_brand_dir(brand) / "analyses" / f"{stamp}.json", result)
    return result


def latest_analysis(brand: str) -> Optional[Dict[str, Any]]:
    folder = _brand_dir(brand) / "analyses"
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    return audience_desk._read(files[-1], None) if files else None


# ──────────────────────────── to the vault ────────────────────────────

def save_idea(brand: str, idea: Dict[str, Any], evidence: List[Dict[str, Any]], *, added_by: str = "user") -> Dict[str, Any]:
    """One analysed idea as a Topic Vault row, the inspiring videos as evidence."""
    from app.services import topic_store

    videos_ev = [{"id": e.get("id"), "title": e.get("title"), "channel": e.get("channel"),
                  "url": e.get("url") or (f"https://www.youtube.com/watch?v={e['id']}" if e.get("id") else ""),
                  "views": e.get("views"), "outlier": e.get("outlier")} for e in evidence or [] if isinstance(e, dict)]
    best = max([float(v.get("outlier") or 0) for v in videos_ev] or [0])
    notes = (f"Our own version of a competitor hit. Angle: {idea.get('angle') or ''} "
             f"Why it could work: {idea.get('why_it_could_work') or ''} "
             f"Format: {idea.get('format') or ''}. Make it with our own research and words; "
             "never reuse their script, footage, thumbnail or exact title.").strip()
    return topic_store.add_topic({
        "topic": str(idea.get("title") or "").strip()[:140], "channel": brand, "category": "Competitor-inspired",
        "source_type": "competitor_inspired", "notes": notes,
        "viral_potential": max(1, min(10, round(4 + min(best, 10) / 2))),
        "evidence": {"videos": videos_ev[:6], "found_at": datetime.now().isoformat(timespec="seconds")},
        "sources_used": [v["url"] for v in videos_ev[:6] if v.get("url")],
    }, added_by=added_by, stage="potential")
