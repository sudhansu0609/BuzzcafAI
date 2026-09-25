"""
Video intelligence (roadmap v6, S1): why a video or channel performs, and how
to model one of the owner's videos after it.

Data comes from yt-dlp without an API key: title, description, tags, views,
likes, comments, duration, upload date, chapters, the "most replayed"
heatmap, captions (the transcript), and a channel's recent uploads (the
baseline the video is measured against). The numbers are computed here; the
reading of them is a model call with the owner's channel guide in context, so
the blueprint is written for *their* channel, not a generic one. When no model
is reachable the metrics-only read is returned and labelled `simulated`.

Results are cached under knowledge/video_intel/<id>.json.
"""

import json
import logging
import os
import re
import statistics
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.video_intel")

STORE_DIR = os.path.join(KNOWLEDGE_DIR, "video_intel")
VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")
BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_RE = re.compile(r"(https?://(?:www\.|m\.)?youtube\.com/(?:@[\w.\-]+|channel/UC[\w\-]+|c/[\w.\-]+|user/[\w.\-]+))", re.I)
HOOK_SECONDS = 45
RECENT_LIMIT = 30


class VideoFetchError(RuntimeError):
    pass


# ───────────────────────── targets ─────────────────────────


def parse_target(url: str) -> Tuple[str, str]:
    """('video', id) or ('channel', canonical url); ValueError for anything else."""
    text = (url or "").strip()
    if not text:
        raise ValueError("Paste a YouTube video or channel link.")
    m = VIDEO_ID_RE.search(text)
    if m:
        return "video", m.group(1)
    if BARE_ID_RE.match(text):
        return "video", text
    m = CHANNEL_RE.search(text)
    if m:
        return "channel", m.group(1).rstrip("/")
    raise ValueError("That does not look like a YouTube video or channel link.")


# ───────────────────────── fetching (yt-dlp) ─────────────────────────


def _ydl(**extra):
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "socket_timeout": 25}
    opts.update(extra)
    return yt_dlp.YoutubeDL(opts)


def fetch_video(video_id: str) -> Dict[str, Any]:
    try:
        with _ydl() as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception as exc:
        raise VideoFetchError(f"YouTube did not return that video: {str(exc).splitlines()[0][:200]}") from exc
    if not info:
        raise VideoFetchError("YouTube returned nothing for that video.")
    return info


def _caption_track(info: Dict[str, Any]) -> Optional[Tuple[str, str, bool]]:
    """(language, json3 url, is_auto) preferring the video's own language, then en, then hi."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    preferred = [lang for lang in (info.get("language"), "en", "hi", "en-US", "en-IN", "hi-IN") if lang]
    for source, is_auto in ((manual, False), (auto, True)):
        langs = list(source.keys())
        ordered = [l for l in preferred if l in source] + [l for l in langs if l.startswith(("en", "hi"))] + langs
        for lang in ordered:
            for fmt in source.get(lang) or []:
                if fmt.get("ext") == "json3" and fmt.get("url"):
                    return lang, fmt["url"], is_auto
    return None


def fetch_transcript(info: Dict[str, Any]) -> Dict[str, Any]:
    track = _caption_track(info)
    if not track:
        return {"language": None, "auto": None, "segments": []}
    lang, url, is_auto = track
    try:
        with _ydl() as ydl:
            raw = ydl.urlopen(url).read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("captions unavailable: %s", exc)
        return {"language": lang, "auto": is_auto, "segments": []}
    segments: List[Dict[str, Any]] = []
    for event in data.get("events") or []:
        text = "".join(seg.get("utf8", "") for seg in event.get("segs") or []).replace("\n", " ").strip()
        if not text:
            continue
        segments.append({"t": round(int(event.get("tStartMs") or 0) / 1000, 1), "text": text})
    return {"language": lang, "auto": is_auto, "segments": segments[:2000]}


def fetch_channel_videos(channel_url: str, limit: int = RECENT_LIMIT) -> List[Dict[str, Any]]:
    try:
        with _ydl(extract_flat=True, playlistend=limit) as ydl:
            info = ydl.extract_info(f"{channel_url.rstrip('/')}/videos", download=False)
    except Exception as exc:
        raise VideoFetchError(f"YouTube did not return that channel's videos: {str(exc).splitlines()[0][:200]}") from exc
    entries = []
    for entry in (info or {}).get("entries") or []:
        if not entry or not entry.get("id"):
            continue
        entries.append({
            "id": entry.get("id"),
            "title": entry.get("title") or "",
            "view_count": int(entry.get("view_count") or 0),
            "duration": int(entry.get("duration") or 0),
            "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
        })
    return entries[:limit]


def search_youtube(query: str, limit: int = 12) -> List[Dict[str, Any]]:
    """Keyless YouTube search via yt-dlp (`ytsearch`), for topic demand/competition.

    Flat extraction, so it stays fast and returns whatever metadata YouTube gives
    for the result rows (view count, duration and upload date are usually present).
    Returns [] on any failure -- no yt-dlp, no network, or a bad query -- so callers
    can treat "no signal" and "search unavailable" the same way.
    """
    q = (query or "").strip()
    if not q:
        return []
    try:
        with _ydl(extract_flat=True, playlistend=limit) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{q}", download=False)
    except Exception as exc:
        logger.warning("youtube search failed for %r: %s", q, str(exc).splitlines()[0][:200])
        return []
    results: List[Dict[str, Any]] = []
    for entry in (info or {}).get("entries") or []:
        if not entry or not entry.get("id"):
            continue
        results.append({
            "id": entry.get("id"),
            "title": entry.get("title") or "",
            "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
            "view_count": int(entry["view_count"]) if entry.get("view_count") is not None else None,
            "duration": int(entry["duration"]) if entry.get("duration") is not None else None,
            "channel": entry.get("channel") or entry.get("uploader") or "",
            "upload_date": entry.get("upload_date"),
        })
    return results[:limit]


# ───────────────────────── metrics ─────────────────────────


def _days_since(upload_date: Optional[str]) -> Optional[float]:
    if not upload_date:
        return None
    try:
        then = datetime.strptime(str(upload_date), "%Y%m%d")
    except ValueError:
        return None
    return max((datetime.now() - then).total_seconds() / 86400, 0.5)


def title_signals(title: str) -> Dict[str, Any]:
    text = title or ""
    words = text.split()
    return {
        "length_chars": len(text),
        "words": len(words),
        "has_number": bool(re.search(r"\d", text)),
        "is_question": text.strip().endswith("?") or bool(re.match(r"^(why|how|what|who|when|where|can|does|is)\b", text, re.I)),
        "has_brackets": bool(re.search(r"[\[\(\|]", text)),
        "caps_words": sum(1 for w in words if len(w) > 2 and w.isupper()),
        "curiosity_words": [w for w in ("secret", "truth", "never", "nobody", "hidden", "why", "real", "mystery", "shocking", "untold")
                            if w in text.lower()],
    }


def _transcript_between(segments: List[Dict[str, Any]], start: float, end: float) -> str:
    return " ".join(s["text"] for s in segments if start <= s["t"] <= end).strip()


def _peaks(heatmap: List[Dict[str, Any]], segments: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    if not heatmap:
        return []
    ranked = sorted(heatmap, key=lambda h: float(h.get("value") or 0), reverse=True)
    peaks: List[Dict[str, Any]] = []
    for cell in ranked:
        start = float(cell.get("start_time") or 0)
        if any(abs(start - p["t"]) < 20 for p in peaks):
            continue
        peaks.append({
            "t": round(start, 1),
            "value": round(float(cell.get("value") or 0), 3),
            "transcript": _transcript_between(segments, start - 10, start + 20)[:400],
        })
        if len(peaks) >= limit:
            break
    return peaks


def _outline(segments: List[Dict[str, Any]], duration: int, samples: int = 8) -> List[Dict[str, Any]]:
    if not segments or not duration:
        return []
    step = duration / samples
    out = []
    for i in range(samples):
        start = i * step
        text = _transcript_between(segments, start, start + min(step, 40))
        if text:
            out.append({"t": round(start), "text": text[:220]})
    return out


def compute_metrics(info: Dict[str, Any], recent: List[Dict[str, Any]], transcript: Dict[str, Any]) -> Dict[str, Any]:
    views = int(info.get("view_count") or 0)
    likes = int(info.get("like_count") or 0)
    comments = int(info.get("comment_count") or 0)
    duration = int(info.get("duration") or 0)
    segments = transcript.get("segments") or []
    days = _days_since(info.get("upload_date"))
    others = [v["view_count"] for v in recent if v.get("id") != info.get("id") and v.get("view_count")]
    median = int(statistics.median(others)) if others else 0
    rank = 1 + sum(1 for v in others if v > views) if others else None
    hook = _transcript_between(segments, 0, HOOK_SECONDS)
    return {
        "views": views,
        "likes": likes,
        "comments": comments,
        "duration_seconds": duration,
        "days_since_upload": round(days, 1) if days else None,
        "views_per_day": round(views / days) if days else None,
        "like_rate_pct": round(likes / views * 100, 2) if views else None,
        "comments_per_1k_views": round(comments / views * 1000, 2) if views else None,
        "channel_followers": info.get("channel_follower_count"),
        "views_to_subs": round(views / info["channel_follower_count"], 2) if info.get("channel_follower_count") else None,
        "recent_median_views": median,
        "outlier_multiple": round(views / median, 2) if median else None,
        "rank_in_recent": rank,
        "videos_sampled": len(others),
        "title": title_signals(info.get("title") or ""),
        "hook_transcript": hook[:900],
        "hook_words_per_second": round(len(hook.split()) / HOOK_SECONDS, 2) if hook else None,
        "peaks": _peaks(info.get("heatmap") or [], segments),
        "chapters": [{"t": int(c.get("start_time") or 0), "title": c.get("title")} for c in (info.get("chapters") or [])][:20],
        "outline": _outline(segments, duration),
        "transcript_words": sum(len(s["text"].split()) for s in segments),
        "transcript_language": transcript.get("language"),
        "transcript_auto": transcript.get("auto"),
        "tags": (info.get("tags") or [])[:25],
    }


def channel_metrics(videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    counted = [v for v in videos if v.get("view_count")]
    views = [v["view_count"] for v in counted]
    median = int(statistics.median(views)) if views else 0
    outliers = sorted(
        ({**v, "outlier_multiple": round(v["view_count"] / median, 2) if median else None} for v in counted),
        key=lambda v: v["view_count"], reverse=True,
    )[:6]
    titles = [v.get("title") or "" for v in videos]
    signals = [title_signals(t) for t in titles]
    durations = [v["duration"] for v in videos if v.get("duration")]
    lead_words: Dict[str, int] = {}
    for t in titles:
        for w in t.lower().split()[:2]:
            w = w.strip("|:-–—,.!?")
            if len(w) > 2:
                lead_words[w] = lead_words.get(w, 0) + 1
    return {
        "videos_sampled": len(videos),
        "median_views": median,
        "mean_views": int(statistics.mean(views)) if views else 0,
        "top_views": max(views) if views else 0,
        "outliers": outliers,
        "median_duration_seconds": int(statistics.median(durations)) if durations else 0,
        "title_patterns": {
            "avg_length_chars": round(statistics.mean(s["length_chars"] for s in signals)) if signals else 0,
            "pct_with_number": round(100 * sum(s["has_number"] for s in signals) / len(signals)) if signals else 0,
            "pct_questions": round(100 * sum(s["is_question"] for s in signals) / len(signals)) if signals else 0,
            "pct_with_brackets": round(100 * sum(s["has_brackets"] for s in signals) / len(signals)) if signals else 0,
            "common_lead_words": sorted(lead_words.items(), key=lambda kv: kv[1], reverse=True)[:8],
        },
    }


# ───────────────────────── the model's reading ─────────────────────────

ANALYST_PROMPT = """You are the Studio's video intelligence analyst for a YouTube creator who runs several channels.
You are given hard numbers (views, engagement, outlier factor against the channel's recent uploads, the
most-replayed moments with what was said there, the opening transcript, title signals, chapters) for a
video that is performing well. Explain *why* it performs, grounded in that evidence, and then write a
blueprint for a new video on the creator's own channel modelled on what works, in the creator's voice
(brand guide below). Be specific: quote the hook, name the technique, give timestamps. Never invent
numbers that are not in the data. Reply in the language the creator writes in (English unless told
otherwise). Answer with ONE JSON object only, no prose around it, with exactly these keys:
{
  "why_it_works": [{"factor": "...", "evidence": "...", "weight": 1-5}],   // 4-7 items, strongest first
  "hook": {"first_line": "...", "technique": "...", "what_it_promises": "..."},
  "structure": [{"t": seconds, "beat": "..."}],                                // 4-8 beats
  "packaging": {"title_pattern": "...", "thumbnail_read": "...", "promise": "..."},
  "audience": {"who": "...", "why_they_click": "...", "why_they_stay": "..."},
  "blueprint": {
    "working_titles": ["...", "...", "..."],
    "hook_script": "the first 30 seconds, written out",
    "outline": [{"segment": "...", "minutes": 0.0, "purpose": "..."}],
    "thumbnail_direction": "...",
    "tags": ["..."],
    "target_length_minutes": 0,
    "cta": "...",
    "differentiator": "what our version does that the original does not"
  },
  "do_not_copy": ["..."]
}"""

CHANNEL_PROMPT = """You are the Studio's channel intelligence analyst for a YouTube creator who runs several channels.
You are given a channel's recent uploads with views, the median, its outliers (videos far above the median)
and title/length patterns. Explain what this channel does that works, what its outliers have in common, and
how the creator can borrow it for their own channel (brand guide below) without copying. Ground every claim
in the listed videos. Answer with ONE JSON object only:
{
  "what_works": [{"factor": "...", "evidence": "...", "weight": 1-5}],
  "outlier_pattern": "...",
  "packaging": {"title_formula": "...", "length": "...", "cadence": "..."},
  "borrow": [{"idea": "...", "for_us": "...", "working_title": "..."}],
  "avoid": ["..."]
}"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start:end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


_llm = None


def _llm_service():
    global _llm
    if _llm is None:
        from integrations.llm import LLMService

        _llm = LLMService()
    if hasattr(_llm, "reload_config"):
        try:
            _llm.reload_config()
        except Exception:
            pass
    return _llm


def _guide(channel: Optional[str]) -> str:
    if not channel:
        return ""
    try:
        from app.services.studio_chat import channel_guide

        return channel_guide(channel)[:3000]
    except Exception:
        return ""


def model_read(system_prompt: str, payload: Dict[str, Any], channel: Optional[str]) -> Tuple[Optional[Dict[str, Any]], bool, str]:
    """(parsed json or None, simulated, raw text)."""
    guide = _guide(channel)
    system = system_prompt + (f"\n\n## The creator's channel to model this for: {channel}\n{guide}" if guide else
                              (f"\n\n## The creator's channel to model this for: {channel}" if channel else ""))
    llm = _llm_service()
    try:
        raw = llm.generate_chat(system, [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], require_json=True)
    except Exception as exc:
        logger.warning("model read failed: %s", exc)
        return None, True, str(exc)
    simulated = bool(getattr(llm, "last_response_simulated", False))
    parsed = None if simulated else _extract_json(str(raw))
    return parsed, simulated or parsed is None, str(raw)


def metrics_only_read(video: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """What the numbers alone say; used, and labelled, when no model answered."""
    factors = []
    if metrics.get("outlier_multiple") and metrics["outlier_multiple"] >= 1.5:
        factors.append({"factor": "Outlier on its own channel", "evidence": f"{metrics['outlier_multiple']}x the median of {metrics['videos_sampled']} recent uploads", "weight": 5})
    if metrics.get("views_to_subs") and metrics["views_to_subs"] >= 1:
        factors.append({"factor": "Reached beyond subscribers", "evidence": f"{metrics['views_to_subs']}x the channel's follower count", "weight": 4})
    if metrics.get("like_rate_pct") and metrics["like_rate_pct"] >= 3:
        factors.append({"factor": "Strong like rate", "evidence": f"{metrics['like_rate_pct']}% of viewers liked it", "weight": 3})
    if metrics.get("comments_per_1k_views") and metrics["comments_per_1k_views"] >= 3:
        factors.append({"factor": "Conversation-driving", "evidence": f"{metrics['comments_per_1k_views']} comments per 1k views", "weight": 3})
    if metrics.get("peaks"):
        first = metrics["peaks"][0]
        factors.append({"factor": "Rewatched moment", "evidence": f"Most replayed at {first['t']}s: \"{first['transcript'][:120]}\"", "weight": 3})
    ts = metrics.get("title") or {}
    if ts.get("curiosity_words") or ts.get("is_question"):
        factors.append({"factor": "Curiosity-led title", "evidence": f"question={ts.get('is_question')}, words={ts.get('curiosity_words')}", "weight": 2})
    if not factors:
        factors.append({"factor": "No standout signal in the numbers", "evidence": "views, engagement and outlier factor are all ordinary", "weight": 1})
    return {
        "why_it_works": factors,
        "hook": {"first_line": (metrics.get("hook_transcript") or "")[:160], "technique": "not assessed (no model)", "what_it_promises": ""},
        "structure": [{"t": c["t"], "beat": c["title"]} for c in metrics.get("chapters") or []][:8]
        or [{"t": o["t"], "beat": o["text"][:80]} for o in metrics.get("outline") or []],
        "packaging": {"title_pattern": video.get("title", ""), "thumbnail_read": "not assessed (no model)", "promise": ""},
        "audience": {"who": "", "why_they_click": "", "why_they_stay": ""},
        "blueprint": {
            "working_titles": [],
            "hook_script": "",
            "outline": [],
            "thumbnail_direction": "",
            "tags": (metrics.get("tags") or [])[:10],
            "target_length_minutes": round((metrics.get("duration_seconds") or 0) / 60),
            "cta": "",
            "differentiator": "",
        },
        "do_not_copy": [],
        "note": "No model was reachable; only the numbers are here. Start a local model or add a key and re-run.",
    }


# ───────────────────────── entry points ─────────────────────────


def _store_path(item_id: str) -> str:
    os.makedirs(STORE_DIR, exist_ok=True)
    return os.path.join(STORE_DIR, f"{re.sub(r'[^A-Za-z0-9_@.-]', '_', item_id)}.json")


def _load(item_id: str) -> Optional[Dict[str, Any]]:
    path = _store_path(item_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _save(item_id: str, data: Dict[str, Any]) -> None:
    with open(_store_path(item_id), "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def video_summary(info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": info.get("id"),
        "url": f"https://www.youtube.com/watch?v={info.get('id')}",
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "handle": info.get("uploader_id"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "thumbnail": info.get("thumbnail"),
        "description": (info.get("description") or "")[:1500],
        "categories": info.get("categories") or [],
        "heatmap": [{"t": round(float(h.get("start_time") or 0)), "v": round(float(h.get("value") or 0), 3)} for h in (info.get("heatmap") or [])][:120],
    }


def analyze_video(video_id: str, channel: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    cached = None if force else _load(video_id)
    if cached and cached.get("channel_for") == (channel or "") and not cached.get("simulated"):
        return cached
    info = fetch_video(video_id)
    transcript = fetch_transcript(info)
    recent: List[Dict[str, Any]] = []
    channel_url = info.get("channel_url") or info.get("uploader_url")
    if channel_url:
        try:
            recent = fetch_channel_videos(channel_url)
        except VideoFetchError as exc:
            logger.warning("channel baseline unavailable: %s", exc)
    metrics = compute_metrics(info, recent, transcript)
    video = video_summary(info)
    payload = {
        "video": {k: video[k] for k in ("title", "channel", "upload_date", "duration", "view_count", "like_count", "comment_count", "categories", "description")},
        "metrics": {k: v for k, v in metrics.items() if k not in ("outline",)},
        "outline": metrics.get("outline"),
        "recent_uploads_sample": [{"title": v["title"], "views": v["view_count"]} for v in recent[:12]],
    }
    analysis, simulated, raw = model_read(ANALYST_PROMPT, payload, channel)
    if analysis is None:
        analysis = metrics_only_read(video, metrics)
    result = {
        "kind": "video",
        "id": video_id,
        "channel_for": channel or "",
        "video": video,
        "metrics": metrics,
        "recent": recent[:RECENT_LIMIT],
        "transcript_excerpt": [s for s in (transcript.get("segments") or []) if s["t"] <= 120][:60],
        "analysis": analysis,
        "simulated": simulated,
        "raw_model_text": "" if not simulated else raw[:1500],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(video_id, result)
    return result


def analyze_channel(channel_url: str, channel: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    key = "channel_" + channel_url.rstrip("/").rsplit("/", 1)[-1]
    cached = None if force else _load(key)
    if cached and cached.get("channel_for") == (channel or "") and not cached.get("simulated"):
        return cached
    videos = fetch_channel_videos(channel_url, limit=RECENT_LIMIT)
    if not videos:
        raise VideoFetchError("No videos were found on that channel.")
    metrics = channel_metrics(videos)
    payload = {
        "channel_url": channel_url,
        "metrics": {k: v for k, v in metrics.items() if k != "outliers"},
        "outliers": [{"title": v["title"], "views": v["view_count"], "outlier_multiple": v.get("outlier_multiple"), "duration": v.get("duration")} for v in metrics["outliers"]],
        "recent_uploads": [{"title": v["title"], "views": v["view_count"], "duration": v.get("duration")} for v in videos],
    }
    analysis, simulated, raw = model_read(CHANNEL_PROMPT, payload, channel)
    if analysis is None:
        analysis = {
            "what_works": [
                {"factor": "Outliers", "evidence": "; ".join(f"{v['title']} ({v['view_count']:,})" for v in metrics["outliers"][:3]), "weight": 4},
                {"factor": "Title habits", "evidence": json.dumps(metrics["title_patterns"], ensure_ascii=False)[:300], "weight": 2},
            ],
            "outlier_pattern": "not assessed (no model)",
            "packaging": {"title_formula": "", "length": f"median {metrics['median_duration_seconds'] // 60} min", "cadence": ""},
            "borrow": [],
            "avoid": [],
            "note": "No model was reachable; only the numbers are here.",
        }
    result = {
        "kind": "channel",
        "id": key,
        "channel_for": channel or "",
        "video": {"channel": channel_url.rstrip("/").rsplit("/", 1)[-1], "url": channel_url, "title": channel_url},
        "metrics": metrics,
        "recent": videos,
        "analysis": analysis,
        "simulated": simulated,
        "raw_model_text": "" if not simulated else raw[:1500],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(key, result)
    return result


def analyze(url: str, channel: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    kind, target = parse_target(url)
    if kind == "video":
        return analyze_video(target, channel, force)
    return analyze_channel(target, channel, force)


def recent_analyses(limit: int = 20) -> List[Dict[str, Any]]:
    if not os.path.isdir(STORE_DIR):
        return []
    items = []
    for name in os.listdir(STORE_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(STORE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            continue
        video = data.get("video") or {}
        items.append({
            "id": data.get("id"),
            "kind": data.get("kind"),
            "title": video.get("title") or video.get("channel"),
            "channel": video.get("channel"),
            "thumbnail": video.get("thumbnail"),
            "view_count": video.get("view_count"),
            "outlier_multiple": (data.get("metrics") or {}).get("outlier_multiple"),
            "channel_for": data.get("channel_for"),
            "simulated": data.get("simulated"),
            "generated_at": data.get("generated_at"),
            "_mtime": os.path.getmtime(path),
        })
    items.sort(key=lambda i: i["_mtime"], reverse=True)
    for item in items:
        item.pop("_mtime", None)
    return items[:limit]


def load_analysis(item_id: str) -> Optional[Dict[str, Any]]:
    return _load(item_id)
