"""
The Audience Desk (2026-10-22): what viewers are asking for, read from the
comments under the creator's own videos and under the big channels in the
same niche, turned into Topic Vault rows with the evidence attached.

Why: the vault was filled by the creator and by web search; nobody read
the comments. On a horror channel the comments ARE the research -- "next
video on X", "mere gaon mein bhi ...", "part 2 kab?", a hundred people
asking for the same haunted fort -- and on a channel with 42 views the
audience to win is the one commenting under Khooni Monday and Scary Pumpkin.

How: no YouTube API key is needed. yt-dlp lists a channel's latest uploads,
searches YouTube for the brand's queries, and pulls each video's top
comments. The comments go to `AudienceResearcher` (local model, JSON) in
batches; its findings are merged, scored by how many viewers said it, how
many liked them and how many different videos it came up under, and kept
under `knowledge/audience/<Brand>/`. A finding becomes a vault row
(`source_type: viewer_requests`, `evidence` with the quotes and the videos)
on request, or the top few by themselves in the nightly run.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.audience_desk")

AUDIENCE_DIR = Path(KNOWLEDGE_DIR) / "audience"
BATCH = 70              # comments per model call
MAX_COMMENTS = 700      # per run, the most liked first
MIN_CHARS = 12          # shorter than this with no "?" is "nice" / an emoji
KEEP_RUNS = 20

KINDS = ("story_request", "question", "own_encounter", "complaint", "praise")
KIND_LABELS = {
    "story_request": "Story requested",
    "question": "Open question",
    "own_encounter": "Viewer's own encounter",
    "complaint": "Complaint",
    "praise": "What they loved",
}
#: Which kinds are worth a vault row (praise and complaints go to the writers
#: and the editor, not the vault).
VAULT_KINDS = ("story_request", "question", "own_encounter")

#: What each channel is, in one line, so the researcher can say whether a
#: request belongs on it (a general creator's video reached through a
#: "haunted fort" search brings requests about politics; those are kept as
#: findings but marked off-niche and never saved by themselves).
NICHE: Dict[str, str] = {
    "Raat3Baje": "Hindi horror storytelling: real encounters, haunted places, rules horror, black magic and tantra stories",
    "Beyond3Baje": "Hindi documentary stories of survival, endurance, mysteries and history",
    "Life3Baje": "Hindi vlog and motivational stories about life, purpose and self-improvement",
    "Khayal3Baje": "Hindi and Urdu poetry, shayari and kavita, read aloud with feeling",
    "Originals": "Hindi storytelling and podcasts",
    "TheTallStoryteller": "Hinglish narrated stories of every genre -- folk tales, mystery, thriller, "
                          "history, mythology, adventure, drama, romance, comedy, classics retold, occasional horror",
}

#: Search queries per brand -- the niche's audience, not the creator's own
#: (his channels are small; the comments to read are under the big ones).
DEFAULT_QUERIES: Dict[str, List[str]] = {
    "Raat3Baje": ["real horror story hindi", "bhootiya kahani sacchi ghatna", "haunted place india horror story hindi",
                  "kala jadu real story hindi", "tantrik real story hindi"],
    "Beyond3Baje": ["survival story hindi documentary", "mystery history hindi", "unsolved mystery hindi real story",
                    "jungle survival true story hindi"],
    "Life3Baje": ["motivational story hindi real life", "life lessons hindi vlog", "self improvement hindi"],
    "Khayal3Baje": ["shayari video hindi urdu", "hindi kavita emotional", "dard bhari shayari"],
    "Originals": ["hindi storytelling channel", "podcast hindi stories"],
    "TheTallStoryteller": ["hindi story channel narration", "hindi kahani sunao", "moral story hindi",
                           "suspense story hindi", "comedy story hindi"],
}


# ──────────────────────────── files ────────────────────────────

def _brand_dir(brand: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", brand or "General")
    return AUDIENCE_DIR / safe


def _read(path: Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def settings() -> Dict[str, Any]:
    data = _read(AUDIENCE_DIR / "settings.json", {})
    return {
        "enabled": bool(data.get("enabled", True)),          # nightly mining
        "max_videos": int(data.get("max_videos", 12)),
        "per_video": int(data.get("per_video", 80)),
        "auto_save_top": int(data.get("auto_save_top", 3)),  # findings per brand saved to the vault by the nightly run
        "last_run": data.get("last_run", ""),
        "last": data.get("last"),
    }


def set_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    data = _read(AUDIENCE_DIR / "settings.json", {})
    for key in ("enabled", "max_videos", "per_video", "auto_save_top", "last_run", "last"):
        if key in patch and patch[key] is not None:
            data[key] = patch[key]
    _write(AUDIENCE_DIR / "settings.json", data)
    return settings()


# ──────────────────────────── sources ────────────────────────────

def _own_channel_ids(brand: str) -> List[str]:
    """The creator's own channel(s) for a brand: the one connected for
    uploads, plus any BuzzBrain channel carrying the brand's name."""
    ids: List[str] = []
    try:
        from integrations import youtube_publish
        cid = youtube_publish.channel_for_brand(brand)
        if cid:
            ids.append(cid)
    except Exception:
        pass
    try:
        index = _read(Path(KNOWLEDGE_DIR) / "buzzbrain" / "index.json", {})
        key = re.sub(r"[^a-z0-9]", "", brand.lower())
        for cid, info in (index.get("channels") or {}).items():
            name = re.sub(r"[^a-z0-9]", "", str(info.get("name") or "").lower())
            if key and name == key and str(cid).startswith("UC") and cid not in ids:
                ids.append(cid)
    except Exception:
        pass
    return ids


def sources(brand: str) -> Dict[str, Any]:
    stored = _read(_brand_dir(brand) / "sources.json", {})
    queries = stored.get("queries")
    if not isinstance(queries, list) or not queries:
        queries = list(DEFAULT_QUERIES.get(brand, ["hindi story channel"]))
    competitors = [c for c in (stored.get("competitors") or []) if isinstance(c, dict) and c.get("url")]
    return {
        "brand": brand,
        "own": stored.get("own") or _own_channel_ids(brand),
        "queries": [str(q).strip() for q in queries if str(q).strip()],
        "competitors": competitors,          # [{url, name, source?, reason?, channel_id?}]
        "excluded": [str(x) for x in (stored.get("excluded") or []) if str(x).strip()],
        "default_queries": DEFAULT_QUERIES.get(brand, []),
    }


def set_sources(brand: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    data = _read(_brand_dir(brand) / "sources.json", {})
    if "queries" in patch and isinstance(patch["queries"], list):
        data["queries"] = [str(q).strip() for q in patch["queries"] if str(q).strip()][:12]
    if "competitors" in patch and isinstance(patch["competitors"], list):
        kept = {str(c.get("url")): c for c in (data.get("competitors") or []) if isinstance(c, dict)}
        rows = []
        for c in patch["competitors"]:
            url = (c.get("url") if isinstance(c, dict) else str(c)).strip() if c else ""
            if not url:
                continue
            if not url.startswith("http"):
                url = f"https://www.youtube.com/{url.lstrip('@') and '@' + url.lstrip('@')}" if not url.startswith("UC")                     else f"https://www.youtube.com/channel/{url}"
            old = kept.get(url) or {}
            src = c if isinstance(c, dict) else {}
            row = {"url": url, "name": src.get("name") or old.get("name") or url.rstrip("/").split("/")[-1]}
            for key in ("source", "reason", "channel_id"):
                val = src.get(key) or old.get(key)
                if val:
                    row[key] = val
            row.setdefault("source", "manual")
            rows.append(row)
        data["competitors"] = rows[:24]
        # a channel the creator adds himself is wanted again: it leaves the excluded list
        added = {x for r in rows if r["source"] != "auto" for x in (r["url"], r.get("channel_id")) if x}
        if added and data.get("excluded"):
            data["excluded"] = [x for x in data["excluded"] if x not in added]
    if "excluded" in patch and isinstance(patch["excluded"], list):
        data["excluded"] = list(dict.fromkeys(str(x).strip() for x in patch["excluded"] if str(x).strip()))
    if "own" in patch and isinstance(patch["own"], list):
        data["own"] = [str(x).strip() for x in patch["own"] if str(x).strip()]
    _write(_brand_dir(brand) / "sources.json", data)
    return sources(brand)


# ──────────────────────────── yt-dlp ────────────────────────────

def _ydl(**extra):
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 25,
            "ignoreerrors": True}
    opts.update(extra)
    return yt_dlp.YoutubeDL(opts)


def _flat_entries(info: Any) -> List[Dict[str, Any]]:
    entries = (info or {}).get("entries") or []
    out = []
    for e in entries:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        out.append({
            "id": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
            "channel_id": e.get("channel_id") or "", "views": int(e.get("view_count") or 0),
            "duration": int(e.get("duration") or 0),
        })
    return out


def channel_uploads(channel: str, limit: int) -> List[Dict[str, Any]]:
    """Latest uploads of a channel id, @handle or channel URL (flat, cheap)."""
    url = channel if channel.startswith("http") else (
        f"https://www.youtube.com/channel/{channel}" if channel.startswith("UC") else f"https://www.youtube.com/@{channel.lstrip('@')}")
    url = url.rstrip("/")
    if not url.endswith("/videos"):
        url += "/videos"
    try:
        with _ydl(extract_flat=True, playlistend=limit) as ydl:
            return _flat_entries(ydl.extract_info(url, download=False))[:limit]
    except Exception as exc:
        logger.warning("audience: could not list %s: %s", channel, str(exc)[:160])
        return []


def search_videos(query: str, limit: int) -> List[Dict[str, Any]]:
    try:
        with _ydl(extract_flat=True) as ydl:
            return _flat_entries(ydl.extract_info(f"ytsearch{limit}:{query}", download=False))
    except Exception as exc:
        logger.warning("audience: search failed for %r: %s", query, str(exc)[:160])
        return []


_EMOJI_ONLY = re.compile(r"^[\W_]+$")


def video_comments(video_id: str, limit: int) -> Dict[str, Any]:
    """The video's top comments (likes first), with the video's own facts."""
    try:
        with _ydl(getcomments=True, noplaylist=True,
                  extractor_args={"youtube": {"max_comments": [str(limit), "all", "20", "5"],
                                              "comment_sort": ["top"]}}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False) or {}
    except Exception as exc:
        logger.warning("audience: comments failed for %s: %s", video_id, str(exc)[:160])
        return {"video_id": video_id, "comments": [], "error": str(exc)[:160]}
    rows = []
    for c in info.get("comments") or []:
        text = re.sub(r"\s+", " ", str(c.get("text") or "")).strip()
        if c.get("author_is_uploader") or not text or _EMOJI_ONLY.match(text):
            continue
        if len(text) < MIN_CHARS and "?" not in text:
            continue
        rows.append({"text": text[:400], "likes": int(c.get("like_count") or 0),
                     "reply": bool(c.get("parent") and c.get("parent") != "root")})
    return {
        "video_id": video_id, "title": info.get("title") or "", "channel": info.get("channel") or info.get("uploader") or "",
        "views": int(info.get("view_count") or 0), "comment_count": int(info.get("comment_count") or 0),
        "comments": rows,
    }


# ──────────────────────────── collecting ────────────────────────────

def collect_videos(brand: str, src: Dict[str, Any], max_videos: int,
                   progress: Callable[[str], None]) -> List[Dict[str, Any]]:
    """Own latest uploads, each competitor's latest, then the search results
    with the most views; deduplicated, no Shorts under a minute."""
    seen: Dict[str, Dict[str, Any]] = {}
    own_ids = set(src.get("own") or [])

    def take(rows: List[Dict[str, Any]], tag: str, cap: int) -> None:
        n = 0
        for r in rows:
            if r["id"] in seen or (r["duration"] and r["duration"] < 60):
                continue
            seen[r["id"]] = {**r, "source": tag}
            n += 1
            if n >= cap:
                break

    for cid in own_ids:
        progress(f"Listing your own uploads ({cid})")
        take(channel_uploads(cid, 6), "own", 4)
    for comp in src.get("competitors") or []:
        progress(f"Listing {comp.get('name') or comp['url']}")
        take(channel_uploads(comp["url"], 4), "competitor", 3)
    found: List[Dict[str, Any]] = []
    for query in src.get("queries") or []:
        progress(f"Searching YouTube: {query}")
        found.extend(r for r in search_videos(query, 10) if r["channel_id"] not in own_ids)
    found.sort(key=lambda r: -r["views"])
    take(found, "search", max(0, max_videos - len(seen)))
    return list(seen.values())[:max_videos]


def collect_comments(videos: List[Dict[str, Any]], per_video: int,
                     progress: Callable[[str], None]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    dedupe = set()
    for i, v in enumerate(videos, 1):
        progress(f"Reading comments {i}/{len(videos)}: {v['title'][:50]}")
        data = video_comments(v["id"], per_video)
        v["title"] = v.get("title") or data.get("title", "")
        v["channel"] = v.get("channel") or data.get("channel", "")
        v["comment_count"] = data.get("comment_count", 0)
        v["comments_read"] = len(data["comments"])
        for c in data["comments"]:
            key = re.sub(r"[^\w]", "", c["text"].lower())[:80]
            if key in dedupe:
                continue
            dedupe.add(key)
            out.append({**c, "video_id": v["id"]})
    out.sort(key=lambda c: -c["likes"])
    return out[:MAX_COMMENTS]


# ──────────────────────────── extracting ────────────────────────────

def _norm_topic(text: str) -> str:
    return re.sub(r"[^\w\s]", "", (text or "").lower()).strip()[:80]


def _batch_findings(brand: str, batch: List[Dict[str, Any]], offset: int) -> List[Dict[str, Any]]:
    from app.services.shorts_desk import _agent_json

    task = {
        "task": "Read these YouTube comments from the channel's niche and list what the viewers are asking for.",
        "brand": brand,
        "channel_is": NICHE.get(brand, "a Hindi storytelling channel"),
        "comments": [{"i": offset + k, "likes": c["likes"], "text": c["text"]} for k, c in enumerate(batch)],
        "answer_format": {
            "findings": [{
                "topic": "one specific story, place, event or question, as a video topic (<= 12 words)",
                "kind": "story_request | question | own_encounter | complaint | praise",
                "in_niche": "true if this could be a video on the channel described in channel_is, else false",
                "why": "one line: what the viewers want from it",
                "comment_ids": ["the i of every comment that asks for this"],
                "quotes": ["up to 3 short verbatim comment fragments"],
            }],
        },
        "rules": [
            "Group the comments that ask for the same thing; one finding per thing.",
            "A finding needs at least one comment id. Never invent a comment.",
            "in_niche is false for requests the channel would never make (politics, news, another creator's series).",
            "Keep topics concrete: 'Bhangarh fort night stay story', not 'more horror'.",
            "A viewer telling their own encounter in the comment is kind own_encounter: keep the place and what happened in the topic.",
            "Comments that only praise, greet or react are kind praise and may be grouped into one finding about what they loved.",
            "Comments about audio, length, upload timing, thumbnails or the host are kind complaint.",
            "Answer with the JSON object only.",
        ],
    }
    data = _agent_json("AudienceResearcher", task) or {}
    rows = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict) or not str(r.get("topic") or "").strip():
            continue
        ids = []
        for x in r.get("comment_ids") or []:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                continue
        kind = str(r.get("kind") or "story_request").strip().lower()
        niche = r.get("in_niche", True)
        if isinstance(niche, str):
            niche = niche.strip().lower() not in ("false", "no", "0")
        out.append({
            "topic": str(r["topic"]).strip()[:140],
            "kind": kind if kind in KINDS else "story_request",
            "in_niche": bool(niche),
            "why": str(r.get("why") or "").strip()[:240],
            "comment_ids": [i for i in ids if 0 <= i - offset < len(batch)] or [],
            "quotes": [str(q).strip()[:200] for q in (r.get("quotes") or []) if str(q).strip()][:3],
        })
    return out


def _consolidate(brand: str, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge findings that batches named differently (one model call)."""
    from app.services.shorts_desk import _agent_json

    if len(findings) < 2:
        return findings
    task = {
        "task": "These findings came from different batches of comments. Merge the ones that mean the same thing.",
        "brand": brand,
        "findings": [{"id": i, "topic": f["topic"], "kind": f["kind"], "mentions": f["mentions"]}
                     for i, f in enumerate(findings)],
        "answer_format": {"groups": [{"topic": "the best wording", "kind": "the kind", "members": ["ids merged into this"]}]},
        "rules": ["Every id appears in exactly one group.", "Only merge the same story, place or question; similar kinds are not enough.",
                  "Answer with the JSON object only."],
    }
    data = _agent_json("AudienceResearcher", task) or {}
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return findings
    used = set()
    merged: List[Dict[str, Any]] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        members = []
        for m in g.get("members") or []:
            try:
                m = int(m)
            except (TypeError, ValueError):
                continue
            if 0 <= m < len(findings) and m not in used:
                members.append(m)
                used.add(m)
        if not members:
            continue
        base = dict(findings[members[0]])
        base["topic"] = str(g.get("topic") or base["topic"]).strip()[:140] or base["topic"]
        for m in members[1:]:
            other = findings[m]
            base["comment_ids"] = sorted(set(base["comment_ids"]) | set(other["comment_ids"]))
            base["quotes"] = (base["quotes"] + [q for q in other["quotes"] if q not in base["quotes"]])[:4]
            base["why"] = base["why"] or other["why"]
            base["in_niche"] = base.get("in_niche", True) and other.get("in_niche", True)
        merged.append(base)
    for i, f in enumerate(findings):
        if i not in used:
            merged.append(dict(f))
    return merged


def extract(brand: str, comments: List[Dict[str, Any]], videos: List[Dict[str, Any]],
            progress: Callable[[str], None]) -> List[Dict[str, Any]]:
    by_topic: Dict[str, Dict[str, Any]] = {}
    batches = [comments[i:i + BATCH] for i in range(0, len(comments), BATCH)]
    for b, batch in enumerate(batches):
        progress(f"Reading what they ask for, batch {b + 1}/{len(batches)}")
        for f in _batch_findings(brand, batch, b * BATCH):
            key = f"{f['kind']}|{_norm_topic(f['topic'])}"
            if key in by_topic:
                cur = by_topic[key]
                cur["comment_ids"] = sorted(set(cur["comment_ids"]) | set(f["comment_ids"]))
                cur["quotes"] = (cur["quotes"] + [q for q in f["quotes"] if q not in cur["quotes"]])[:4]
                cur["in_niche"] = cur.get("in_niche", True) and f.get("in_niche", True)
            else:
                by_topic[key] = f
    findings = list(by_topic.values())
    for f in findings:
        f["mentions"] = len(f["comment_ids"])
    if len(findings) > 12:
        progress("Merging findings that say the same thing")
        findings = _consolidate(brand, findings)
    titles = {v["id"]: v for v in videos}
    for f in findings:
        ids = [i for i in f["comment_ids"] if 0 <= i < len(comments)]
        f["comment_ids"] = ids
        f["mentions"] = len(ids)
        f["likes"] = sum(comments[i]["likes"] for i in ids)
        vids = sorted({comments[i]["video_id"] for i in ids})
        f["videos"] = [{"id": v, "title": titles.get(v, {}).get("title", ""), "channel": titles.get(v, {}).get("channel", "")}
                       for v in vids]
        if not f["quotes"]:
            f["quotes"] = [comments[i]["text"][:200] for i in ids[:3]]
        # Demand: how many said it, how many agreed, how many videos it came up under.
        f["score"] = round(f["mentions"] * 3 + math.log1p(f["likes"]) * 2 + len(vids) * 4, 1)
        f["kind_label"] = KIND_LABELS.get(f["kind"], f["kind"])
        f.setdefault("in_niche", True)
    findings = [f for f in findings if f["mentions"] > 0]
    # The channel's own material first; off-niche requests stay visible at the end.
    findings.sort(key=lambda f: (not f["in_niche"], -f["score"], f["topic"]))
    return findings


# ──────────────────────────── runs ────────────────────────────

def run(brand: str, max_videos: Optional[int] = None, per_video: Optional[int] = None,
        progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    say = progress or (lambda m: None)
    conf = settings()
    max_videos = max(2, min(30, int(max_videos or conf["max_videos"])))
    per_video = max(10, min(200, int(per_video or conf["per_video"])))
    t0 = time.time()
    src = sources(brand)
    videos = collect_videos(brand, src, max_videos, say)
    if not videos:
        raise RuntimeError("No videos found for the brand's sources; check the queries and competitor channels.")
    comments = collect_comments(videos, per_video, say)
    findings = extract(brand, comments, videos, say) if comments else []
    record = {
        "brand": brand, "ran_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0),
        "videos": videos, "comments_read": len(comments),
        "findings": findings,
        "sources": {"own": src["own"], "queries": src["queries"], "competitors": src["competitors"]},
    }
    _write(_brand_dir(brand) / "latest.json", record)
    _write(_brand_dir(brand) / "runs" / f"{record['ran_at'].replace(':', '-')}.json", record)
    runs = sorted((_brand_dir(brand) / "runs").glob("*.json"))
    for old in runs[:-KEEP_RUNS]:
        try:
            old.unlink()
        except OSError:
            pass
    say(f"Done: {len(findings)} findings from {len(comments)} comments under {len(videos)} videos")
    return record


def latest(brand: str) -> Optional[Dict[str, Any]]:
    data = _read(_brand_dir(brand) / "latest.json", None)
    return data if isinstance(data, dict) else None


def history(brand: str) -> List[Dict[str, Any]]:
    rows = []
    for path in sorted((_brand_dir(brand) / "runs").glob("*.json"), reverse=True):
        rec = _read(path, None)
        if isinstance(rec, dict):
            rows.append({"ran_at": rec.get("ran_at"), "videos": len(rec.get("videos") or []),
                         "comments_read": rec.get("comments_read", 0), "findings": len(rec.get("findings") or [])})
    return rows


# ──────────────────────────── to the vault ────────────────────────────

def _category(kind: str) -> str:
    return {"story_request": "Viewer request", "question": "Viewer question", "own_encounter": "Viewer encounter"}.get(kind, "Viewer request")


def save_to_vault(brand: str, finding: Dict[str, Any], *, added_by: str = "audience_desk") -> Dict[str, Any]:
    """One finding as a vault row (updated in place when the topic exists)."""
    from app.services import topic_store

    mentions = int(finding.get("mentions") or 0)
    likes = int(finding.get("likes") or 0)
    videos = finding.get("videos") or []
    quotes = finding.get("quotes") or []
    where = ", ".join(f"{v.get('channel') or '?'}: {v.get('title') or v.get('id')}" for v in videos[:3])
    notes = (f"Asked by {mentions} viewer{'s' if mentions != 1 else ''} "
             f"(comments liked {likes} times) under {len(videos)} video{'s' if len(videos) != 1 else ''}. "
             + (f"{finding.get('why')} " if finding.get("why") else "")
             + (f"Quotes: " + " | ".join(f'"{q}"' for q in quotes[:3]) + ". " if quotes else "")
             + (f"Seen under: {where}." if where else ""))
    row = topic_store.add_topic({
        "topic": finding["topic"], "channel": brand, "category": _category(finding.get("kind", "")),
        "source_type": "viewer_requests", "notes": notes,
        "viral_potential": max(1, min(10, round(2 + math.log1p(mentions) * 2 + min(len(videos), 3)))),
        "evidence": {"kind": finding.get("kind"), "mentions": mentions, "likes": likes, "score": finding.get("score"),
                     "quotes": quotes[:4], "videos": videos[:6], "found_at": datetime.now().isoformat(timespec="seconds")},
        "sources_used": [f"https://www.youtube.com/watch?v={v['id']}" for v in videos[:6] if v.get("id")],
    }, added_by=added_by, stage="potential")
    # Remember on the run that this one is in the vault.
    rec = latest(brand)
    if rec:
        for f in rec.get("findings") or []:
            if f.get("topic") == finding.get("topic") and f.get("kind") == finding.get("kind"):
                f["saved_topic_id"] = row["id"]
        _write(_brand_dir(brand) / "latest.json", rec)
    return row


def _already_in_vault(brand: str, topic: str) -> bool:
    from app.services import topic_store

    key = _norm_topic(topic)
    for row in topic_store.load_topics():
        if row.get("channel") == brand and _norm_topic(row.get("topic", "")) == key:
            return True
    return False


def run_all(progress: Optional[Callable[[str], None]] = None, brands: Optional[List[str]] = None) -> Dict[str, Any]:
    """The nightly pass: every brand with queries, the top findings into the vault."""
    say = progress or (lambda m: None)
    conf = settings()
    if brands is None:
        from integrations.youtube_publish import brands as all_brands
        brands = [b for b in all_brands() if b in DEFAULT_QUERIES or (_brand_dir(b) / "sources.json").exists()]
    done, saved, failed = [], [], []
    for brand in brands:
        # Master pause (docs/STUDIO_DIRECTOR_PLAN.md Part 1): between
        # brands, before the next one's comment mining starts.
        from app.services import master_control
        master_control.wait_if_paused(f"audience_desk: {brand}", say)
        try:
            rec = run(brand, progress=lambda m, b=brand: say(f"{b}: {m}"))
        except Exception as exc:  # noqa: BLE001 - one brand must not stop the rest
            logger.exception("audience: %s failed", brand)
            failed.append({"brand": brand, "error": str(exc)[:200]})
            continue
        done.append({"brand": brand, "videos": len(rec["videos"]), "comments": rec["comments_read"],
                     "findings": len(rec["findings"]), "seconds": rec["seconds"]})
        n = 0
        for f in rec["findings"]:
            if n >= conf["auto_save_top"]:
                break
            if f["kind"] not in VAULT_KINDS or f["mentions"] < 2 or not f.get("in_niche", True) \
                    or _already_in_vault(brand, f["topic"]):
                continue
            row = save_to_vault(brand, f, added_by="nightly")
            saved.append({"brand": brand, "topic": row["topic"], "mentions": f["mentions"], "id": row["id"]})
            n += 1
    record = {"ran_at": datetime.now().isoformat(timespec="seconds"), "done": done, "saved": saved, "failed": failed}
    set_settings({"last_run": datetime.now().date().isoformat(), "last": record})
    return record


# ──────────────────────────── jobs ────────────────────────────

_jobs: Dict[str, Dict[str, Any]] = {}


def start_job(kind: str, fn: Callable[..., Any], *args: Any) -> Dict[str, Any]:
    from integrations import idle_offload

    job_id = uuid.uuid4().hex[:12]
    job = {"job_id": job_id, "kind": kind, "state": "running", "message": "Starting", "result": None,
           "error": None, "started_at": datetime.now().isoformat(timespec="seconds")}
    _jobs[job_id] = job

    def progress(msg: str) -> None:
        job["message"] = msg

    def go() -> None:
        try:
            with idle_offload.busy():
                job["result"] = fn(*args, progress=progress)
            job["state"] = "done"
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            logger.exception("audience %s job failed", kind)
            job.update(state="failed", error=str(exc)[:300], message=f"Failed: {str(exc)[:120]}")
        finally:
            idle_offload.offload_now(f"audience {kind} finished")

    threading.Thread(target=go, name=f"audience-{kind}-{job_id}", daemon=True).start()
    return job


def job(job_id: str) -> Optional[Dict[str, Any]]:
    return _jobs.get(job_id)
