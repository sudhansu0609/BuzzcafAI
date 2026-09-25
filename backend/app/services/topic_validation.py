"""
Topic demand validation (roadmap v12): before a topic becomes a project, check
whether it is worth making -- real audience demand, how saturated the competition
already is, and a clear make / refine / skip call.

Keyless and privacy-safe, reusing the signals the Studio already has:
- YouTube competition via yt-dlp search (app.services.video_intel.search_youtube)
- General web interest via the anonymous web research service (web_research)
- Google Trends interest-over-time, best-effort only (optional pytrends; never
  a hard dependency, and it degrades to "unavailable" rather than failing).

The verdict is a model call grounded in that evidence with the channel's brand
guide in context. When no model is reachable a metrics-only verdict is returned
and labelled `simulated`, the same honesty pattern as video_intel.

Results are cached under knowledge/topic_validation/<slug>.json.
"""

import json
import logging
import os
import re
import statistics
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.topic_validation")

STORE_DIR = os.path.join(KNOWLEDGE_DIR, "topic_validation")


# ───────────────────────── evidence: signals ─────────────────────────


def _significant_words(text: str) -> List[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) > 3]


def _youtube_stats(entries: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    """Demand/competition numbers computed from YouTube search rows."""
    views = [e["view_count"] for e in entries if e.get("view_count")]
    durations = [e["duration"] for e in entries if e.get("duration")]
    q_words = set(_significant_words(query))

    dated = recent = 0
    for e in entries:
        d = str(e.get("upload_date") or "")
        if len(d) == 8:
            dated += 1
            try:
                then = datetime.strptime(d, "%Y%m%d")
            except ValueError:
                continue
            if (datetime.now() - then).days <= 365:
                recent += 1

    overlap = 0
    for e in entries:
        if len(q_words & set(_significant_words(e.get("title", "")))) >= 2:
            overlap += 1

    n = len(entries)
    return {
        "results": n,
        "with_view_counts": len(views),
        "median_views": int(statistics.median(views)) if views else None,
        "max_views": max(views) if views else None,
        "avg_duration_seconds": int(statistics.mean(durations)) if durations else None,
        "recent_share_pct": round(100 * recent / dated) if dated else None,
        "title_saturation_pct": round(100 * overlap / n) if n else 0,
    }


def _web_interest(query: str) -> List[Dict[str, str]]:
    try:
        from app.services.web_research import search_web

        return search_web(query, max_results=5)
    except Exception as exc:
        logger.warning("web interest lookup failed: %s", exc)
        return []


def _source_material(query: str) -> Dict[str, Any]:
    """Best-effort news/book source material from the deep research helper.

    Lazily imported and never a hard dependency: a missing module or a lookup
    failure just means this signal is empty, same pattern as web/trends.
    """
    try:
        from app.services.deep_research import deep_research

        return deep_research(query, kinds=("news", "books"), per_source=3) or {}
    except Exception as exc:
        logger.warning("source material lookup failed: %s", exc)
        return {}


def google_trends_interest(query: str) -> Dict[str, Any]:
    """Best-effort Google Trends interest-over-time (last 12 months).

    Optional: pytrends is imported lazily and any failure -- not installed, rate
    limited, no data -- returns an `available: False` note instead of raising.
    Google Trends has no keyless official API, so this is the one signal that may
    simply be absent; the verdict still stands on YouTube and web evidence.
    """
    q = (query or "").strip()
    if not q:
        return {"available": False, "note": "empty query"}
    try:
        from pytrends.request import TrendReq
    except Exception:
        return {"available": False, "note": "pytrends not installed; Google Trends signal skipped."}
    try:
        pt = TrendReq(hl="en-US", tz=330, timeout=(4, 8))
        kw = q[:100]
        pt.build_payload([kw], timeframe="today 12-m")
        frame = pt.interest_over_time()
        if frame is None or getattr(frame, "empty", True) or kw not in frame:
            return {"available": False, "note": "no Google Trends data for this query."}
        series = [int(v) for v in frame[kw].tolist() if v is not None]
        if not series:
            return {"available": False, "note": "no Google Trends data points."}
        half = len(series) // 2 or 1
        first_avg = sum(series[:half]) / half
        second_avg = sum(series[half:]) / max(len(series) - half, 1)
        if second_avg > first_avg * 1.15:
            trend = "rising"
        elif second_avg < first_avg * 0.85:
            trend = "falling"
        else:
            trend = "flat"
        return {"available": True, "avg": round(sum(series) / len(series), 1), "latest": series[-1], "trend": trend}
    except Exception as exc:
        logger.warning("google trends lookup failed for %r: %s", q, exc)
        return {"available": False, "note": "Google Trends lookup failed or was rate limited."}


# ───────────────────────── the model's verdict ─────────────────────────


VALIDATION_PROMPT = """You are the Studio's topic scout for a YouTube creator who runs several channels.
You are given a proposed video topic plus hard evidence: YouTube search results for it (view counts,
how recent they are, how saturated the titles are), general web coverage, and -- when available -- a
Google Trends interest-over-time read. Judge whether the creator should make this video for the named
channel. Weigh real demand against how crowded the space already is, and name the angle that is still
open. Ground every claim in the evidence and never invent numbers. Reply in the creator's language
(English unless told otherwise). Answer with ONE JSON object only, no prose around it, exactly these keys:
{
  "demand": {"score": 1-10, "reason": "..."},
  "competition": {"level": "low|medium|high", "saturation": "...", "note": "..."},
  "differentiation": {"angle": "...", "gap": "..."},
  "audience_fit": "how it fits this channel",
  "recommendation": "make|refine|skip",
  "confidence": 1-10,
  "reasons": ["...", "..."],
  "suggested_title": "...",
  "risks": ["..."],
  "top_competitors": [{"title": "...", "views": 0, "url": "..."}],
  "alternatives": [{"topic": "...", "why": "..."}]
}"""


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


def _metrics_only_verdict(stats: Dict[str, Any], youtube: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What the numbers alone say; used, and labelled, when no model answered."""
    sat = stats.get("title_saturation_pct") or 0
    median = stats.get("median_views")
    results = stats.get("results") or 0

    if results == 0:
        rec, level, score, reason = "refine", "low", 4, "No YouTube results were retrieved, so demand could not be measured from search."
    elif sat >= 70:
        rec, level, score, reason = "refine", "high", 6, f"{sat}% of the top results reuse this topic's words -- crowded; find a sharper angle before committing."
    elif median and median >= 100000 and sat < 50:
        rec, level, score, reason = "make", "medium", 8, f"Comparable videos pull a median of {median:,} views and the titles are not saturated -- clear room to enter."
    elif median and median >= 20000:
        rec, level, score, reason = "make", "medium", 7, f"Solid interest (median {median:,} views) with the title space only partly taken."
    else:
        rec, level, score, reason = "refine", "medium", 5, "Interest looks modest in the numbers; sharpen the hook or pick a stronger angle."

    return {
        "demand": {"score": score, "reason": reason},
        "competition": {"level": level, "saturation": f"{sat}% of top results reuse the topic's words", "note": "not assessed (no model)"},
        "differentiation": {"angle": "not assessed (no model)", "gap": ""},
        "audience_fit": "",
        "recommendation": rec,
        "confidence": 3,
        "reasons": [reason],
        "suggested_title": "",
        "risks": [],
        "top_competitors": [{"title": e.get("title"), "views": e.get("view_count"), "url": e.get("url")} for e in youtube[:5]],
        "alternatives": [],
        "note": "No model was reachable; this verdict is from the numbers only. Start a local model or add a key and re-run.",
    }


# ───────────────────────── entry point ─────────────────────────


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip().lower()).strip("_")[:80] or "topic"


def _store_path(topic: str, channel: Optional[str]) -> str:
    os.makedirs(STORE_DIR, exist_ok=True)
    return os.path.join(STORE_DIR, f"{_slug(topic)}__{_slug(channel or 'any')}.json")


def validate_topic(topic: str, channel: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Assemble the evidence, get the verdict, and return the full dossier.

    Never raises for a missing signal or a missing model: a search or trends
    failure is folded into the evidence, and a missing model yields a
    metrics-only verdict flagged `simulated`.
    """
    clean = (topic or "").strip()
    if not clean:
        return {
            "topic": topic, "channel": channel or "", "verdict": None, "simulated": True,
            "error": "No topic provided.", "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    path = _store_path(clean, channel)
    if not force:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                cached = json.load(handle)
            if not cached.get("simulated"):
                return cached
        except Exception:
            pass

    from app.services.video_intel import search_youtube, _extract_json

    youtube = search_youtube(clean, limit=12)
    stats = _youtube_stats(youtube, clean)
    web = _web_interest(clean)
    trends = google_trends_interest(clean)
    sources = _source_material(clean)

    payload = {
        "topic": clean,
        "channel": channel or "",
        "youtube_stats": stats,
        "top_youtube": [
            {"title": e.get("title"), "views": e.get("view_count"), "url": e.get("url"), "upload_date": e.get("upload_date")}
            for e in youtube[:8]
        ],
        "web": [{"title": r.get("title"), "snippet": r.get("snippet"), "url": r.get("url")} for r in web],
        "trends": trends,
        "source_material": {
            "sources_searched": sources.get("sources_searched") or [],
            "titles": [r.get("title") for r in (sources.get("results") or [])[:5]],
        },
    }

    guide = _guide(channel)
    system = VALIDATION_PROMPT + (
        f"\n\n## The creator's channel this is for: {channel}\n{guide}" if guide else
        (f"\n\n## The creator's channel this is for: {channel}" if channel else "")
    )

    llm = _llm_service()
    verdict = None
    simulated = False
    try:
        raw = llm.generate_chat(system, [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], require_json=True)
        simulated = bool(getattr(llm, "last_response_simulated", False))
        if not simulated:
            verdict = _extract_json(str(raw))
    except Exception as exc:
        logger.warning("topic validation model read failed: %s", exc)
        simulated = True

    if verdict is None:
        verdict = _metrics_only_verdict(stats, youtube)
        simulated = True

    steps = [
        {"step": 1, "source": "YouTube search", "detail": clean, "count": len(youtube)},
        {"step": 2, "source": "Web search", "count": len(web)},
        {"step": 3, "source": "Google Trends", "status": "available" if trends.get("available") else "unavailable", "detail": trends.get("note", "")},
        {"step": 4, "source": "Public archives & news", "count": len((sources or {}).get("results", []))},
        {"step": 5, "source": "Model verdict", "status": "simulated" if simulated else "model"},
    ]

    result = {
        "topic": clean,
        "channel": channel or "",
        "evidence": {"youtube": youtube, "youtube_stats": stats, "web": web, "trends": trends, "sources": sources},
        "verdict": verdict,
        "simulated": simulated,
        "steps": steps,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("could not cache topic validation: %s", exc)

    return result
