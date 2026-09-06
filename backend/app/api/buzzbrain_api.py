"""
BuzzBrain snapshots (roadmap v5, 5.1).

The BuzzBrain Chrome extension scrapes every YouTube watch page the owner
visits and computes per-video metrics, then throws them away on navigation.
This router keeps them: every snapshot is appended to
`knowledge/buzzbrain/snapshots.jsonl` and an `index.json` holds the latest
record per video and per channel, so Dexter can answer "how is my latest
video doing" and "how are my channels doing" from real numbers.

A video is *mine* when its channel id is in the Studio setting
`owner_channel_ids`, or when its channel name matches one of the brands the
Studio produces for. Nothing else is ever treated as the owner's.
"""

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.events import bus
from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.buzzbrain")

router = APIRouter(prefix="/api/buzzbrain", tags=["BuzzBrain"])

BUZZBRAIN_DIR = os.path.join(KNOWLEDGE_DIR, "buzzbrain")
SNAPSHOTS_PATH = os.path.join(BUZZBRAIN_DIR, "snapshots.jsonl")
INDEX_PATH = os.path.join(BUZZBRAIN_DIR, "index.json")
MAX_HISTORY_PER_VIDEO = 200
_lock = threading.Lock()


class SnapshotSchema(BaseModel):
    captured_at: Optional[str] = None
    source: Optional[str] = "buzzbrain"
    version: Optional[str] = None
    reason: Optional[str] = None
    videoMeta: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    keywords: Optional[Dict[str, Any]] = None
    competitor: Optional[Dict[str, Any]] = None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _owner_ids() -> List[str]:
    try:
        from integrations.llm import load_config

        ids = load_config().get("owner_channel_ids") or []
        return [str(i).strip() for i in ids if str(i).strip()]
    except Exception:
        return []


def _brand_slugs() -> List[str]:
    try:
        from app.main import get_brands

        return [_slug(b) for b in get_brands()]
    except Exception:
        return []


def is_mine(channel_id: str, channel_name: str) -> Dict[str, Any]:
    if channel_id and channel_id in _owner_ids():
        return {"mine": True, "reason": "channel_id"}
    if channel_name and _slug(channel_name) in _brand_slugs():
        return {"mine": True, "reason": "brand_name"}
    return {"mine": False, "reason": None}


def _load_index() -> Dict[str, Any]:
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data.setdefault("videos", {})
            data.setdefault("channels", {})
            return data
    except Exception:
        pass
    return {"last_snapshot_at": None, "count": 0, "videos": {}, "channels": {}}


def _save_index(index: Dict[str, Any]) -> None:
    os.makedirs(BUZZBRAIN_DIR, exist_ok=True)
    tmp = INDEX_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2)
    os.replace(tmp, INDEX_PATH)


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _record(snapshot: SnapshotSchema) -> Dict[str, Any]:
    meta = snapshot.videoMeta or {}
    metrics = snapshot.metrics or {}
    video_id = str(meta.get("videoId") or "").strip()
    if not video_id:
        raise HTTPException(status_code=422, detail="videoMeta.videoId is required")
    captured = snapshot.captured_at or datetime.now(timezone.utc).isoformat()
    channel_id = str(meta.get("channelId") or "").strip()
    channel_name = str(meta.get("channelName") or "").strip()
    ownership = is_mine(channel_id, channel_name)
    return {
        "captured_at": captured,
        "source": snapshot.source or "buzzbrain",
        "version": snapshot.version,
        "reason": snapshot.reason,
        "video_id": video_id,
        "title": meta.get("title"),
        "channel_id": channel_id,
        "channel_name": channel_name,
        "mine": ownership["mine"],
        "mine_reason": ownership["reason"],
        "is_shorts": bool(meta.get("isShorts")),
        "is_monetized": meta.get("isMonetized"),
        "publish_date": meta.get("publishDate"),
        "published_ago": meta.get("publishedAgo"),
        "duration_seconds": _number(meta.get("durationSeconds")),
        "watch_percent": _number(meta.get("watchPercent")),
        "views": _number(meta.get("viewCount")),
        "likes": _number(meta.get("likeCount")),
        "comments": _number(meta.get("commentCount")),
        "subscribers": _number(meta.get("subscriberCount")),
        "tags": meta.get("tags") if isinstance(meta.get("tags"), list) else [],
        "category": meta.get("category"),
        "vph": _number(metrics.get("vph")),
        "like_ratio": _number(metrics.get("likeRatio")),
        "engagement_rate": _number(metrics.get("totalEngagementRate")),
        "niche": metrics.get("detectedNiche"),
        "rpm_min": _number(metrics.get("estimatedRpmMin")),
        "rpm_max": _number(metrics.get("estimatedRpmMax")),
        "earnings_min": _number(metrics.get("estimatedVideoEarningsMin")),
        "earnings_max": _number(metrics.get("estimatedVideoEarningsMax")),
        "outlier": metrics.get("outlierBadge"),
        "seo_score": _number((snapshot.keywords or {}).get("seoScore")),
        "title_hook_score": _number((snapshot.keywords or {}).get("titleHookScore")),
    }


@router.post("/snapshot")
def ingest_snapshot(snapshot: SnapshotSchema):
    record = _record(snapshot)
    with _lock:
        os.makedirs(BUZZBRAIN_DIR, exist_ok=True)
        with open(SNAPSHOTS_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        index = _load_index()
        index["last_snapshot_at"] = record["captured_at"]
        index["count"] = int(index.get("count") or 0) + 1
        video = index["videos"].get(record["video_id"]) or {"first_seen": record["captured_at"], "history": 0}
        video.update({"latest": record, "history": int(video.get("history") or 0) + 1, "last_seen": record["captured_at"]})
        index["videos"][record["video_id"]] = video
        key = record["channel_id"] or _slug(record["channel_name"]) or "unknown"
        channel = index["channels"].get(key) or {"first_seen": record["captured_at"], "videos": []}
        channel.update({
            "channel_id": record["channel_id"],
            "name": record["channel_name"] or channel.get("name"),
            "mine": record["mine"],
            "subscribers": record["subscribers"] if record["subscribers"] is not None else channel.get("subscribers"),
            "last_seen": record["captured_at"],
        })
        if record["video_id"] not in channel["videos"]:
            channel["videos"].append(record["video_id"])
        index["channels"][key] = channel
        _save_index(index)
    bus.publish("buzzbrain_snapshot", {
        "video_id": record["video_id"], "title": record["title"], "channel": record["channel_name"],
        "mine": record["mine"], "views": record["views"], "vph": record["vph"], "reason": record["reason"],
    })
    return {"status": "stored", "video_id": record["video_id"], "mine": record["mine"], "count": index["count"]}


@router.get("/latest")
def latest(n: int = Query(5, ge=1, le=50), mine: Optional[bool] = None):
    index = _load_index()
    videos = list(index["videos"].values())
    if mine is not None:
        videos = [v for v in videos if bool((v.get("latest") or {}).get("mine")) == mine]
    videos.sort(key=lambda v: v.get("last_seen") or "", reverse=True)
    return {
        "last_snapshot_at": index.get("last_snapshot_at"),
        "count": index.get("count", 0),
        "videos": [v["latest"] for v in videos[:n] if v.get("latest")],
    }


@router.get("/channels")
def channels():
    index = _load_index()
    out = []
    for key, channel in index["channels"].items():
        vids = [index["videos"][v]["latest"] for v in channel.get("videos", []) if v in index["videos"]]
        vids.sort(key=lambda r: r.get("captured_at") or "", reverse=True)
        best = max((r.get("vph") or 0 for r in vids), default=0)
        out.append({
            "key": key,
            "channel_id": channel.get("channel_id"),
            "name": channel.get("name"),
            "mine": bool(channel.get("mine")),
            "subscribers": channel.get("subscribers"),
            "videos_seen": len(vids),
            "last_seen": channel.get("last_seen"),
            "best_vph": best,
            "latest_video": vids[0] if vids else None,
        })
    out.sort(key=lambda c: (not c["mine"], c.get("last_seen") or ""), reverse=False)
    return {"last_snapshot_at": index.get("last_snapshot_at"), "channels": out}


@router.get("/videos/{video_id}")
def video_history(video_id: str, limit: int = Query(50, ge=1, le=500)):
    index = _load_index()
    entry = index["videos"].get(video_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"No snapshots for video {video_id}")
    history: List[Dict[str, Any]] = []
    try:
        with open(SNAPSHOTS_PATH, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if record.get("video_id") == video_id:
                    history.append({
                        "captured_at": record.get("captured_at"), "views": record.get("views"),
                        "likes": record.get("likes"), "comments": record.get("comments"),
                        "vph": record.get("vph"), "watch_percent": record.get("watch_percent"),
                        "reason": record.get("reason"),
                    })
    except FileNotFoundError:
        pass
    return {"video_id": video_id, "latest": entry.get("latest"), "history": history[-limit:]}
