"""Single source of truth for the saved-topic vault.

Every place that reads or writes ``backend/knowledge/saved_topics.json`` --
the `/api/topics/*` endpoints in `app.main`, and anything else that needs the
vault -- should go through this module instead of touching the file
directly, so the on-disk shape, the seed-on-empty behaviour and the new
lifecycle `stage` field live in exactly one place.
"""
import os
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR

# Kept for readability / anything that wants "the" path, but every read and
# write below recomputes the path from `KNOWLEDGE_DIR` at call time (not just
# once, here, at import time) so a test that monkeypatches this module's
# `KNOWLEDGE_DIR` after import still lands every subsequent read/write there.
SAVED_TOPICS_FILE = os.path.join(KNOWLEDGE_DIR, "saved_topics.json")

STAGES = ["backlog", "potential", "researching", "in_progress", "published"]
DEFAULT_STAGE = "backlog"


def _normalize_stage(stage: Optional[str]) -> str:
    if isinstance(stage, str):
        candidate = stage.strip().lower()
        if candidate in STAGES:
            return candidate
    return DEFAULT_STAGE


def _saved_topics_file() -> str:
    return os.path.join(KNOWLEDGE_DIR, "saved_topics.json")


def load_topics() -> List[Dict[str, Any]]:
    """Read the vault, seeding it the first time it is touched.

    An empty or truncated file is treated as "never seeded" -- otherwise the
    vault stays permanently empty because the file technically exists.
    """
    path = _saved_topics_file()
    needs_seed = not os.path.exists(path) or os.path.getsize(path) == 0
    if needs_seed:
        initial_topics = [
            {
                "id": "saved_topic_1",
                "topic": "Bhangarh Fort Ka Wo Guard Jo Raat Ke 3 Baje Ghaayab Ho Gaya",
                "category": "Paranormal & Haunted Locations",
                "channel": "Raat3Baje",
                "viral_potential": 9,
                "country": "India",
                "source_type": "Local Indian Folklore & Archives",
                "sources_used": ["Reddit (r/Paranormal)", "Local Rajasthani Folklore"],
                "visual_requirements": ["Haunted fort archival photos", "Night rain mist imagery"],
                "exclusion_audit": "✓ Verified: Parapsychological Folklore",
                "notes": "Focus on the 3AM guard shift testimonies written in Hinglish script",
                "saved_at": datetime.now().isoformat()
            },
            {
                "id": "saved_topic_2",
                "topic": "Kaise Ek Choti Si Engineering Galti Ne Poore Warship Ko Duba Diya",
                "category": "Engineering & Disaster Stories",
                "channel": "Beyond3Baje",
                "viral_potential": 9,
                "country": "International",
                "source_type": "Historical & Technical Archives",
                "sources_used": ["Naval Inspection Records", "Wikipedia Disasters"],
                "visual_requirements": ["Ship cross-section 3D diagram", "17th Century maps"],
                "exclusion_audit": "✓ EXCLUSION VERIFIED: 100% Real-World True Story in Hinglish",
                "notes": "Use 3D stability diagram for 45-second Hinglish opening hook",
                "saved_at": datetime.now().isoformat()
            }
        ]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(initial_topics, f, indent=2)
        return initial_topics
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_topics(topics: List[Dict[str, Any]]) -> None:
    """Atomic write: never leaves a half-written vault on disk."""
    path = _saved_topics_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(topics, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def add_topic(fields: Dict[str, Any], *, added_by: str = "user", stage: Optional[str] = None) -> Dict[str, Any]:
    """Save (or update, if the same topic+channel already exists) a row."""
    topic_data = dict(fields)
    if not topic_data.get("id"):
        topic_data["id"] = f"topic_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    topic_data["saved_at"] = now
    topic_data["updated_at"] = now
    topic_data["added_by"] = topic_data.get("added_by") or added_by
    topic_data["stage"] = _normalize_stage(topic_data.get("stage") or stage)

    topics = load_topics()
    existing_idx = next(
        (i for i, t in enumerate(topics) if t.get("topic") == topic_data.get("topic") and t.get("channel") == topic_data.get("channel")),
        -1,
    )
    if existing_idx >= 0:
        topics[existing_idx].update(topic_data)
        stored = topics[existing_idx]
    else:
        topics.insert(0, topic_data)
        stored = topic_data

    save_topics(topics)
    return stored


def update_topic(topic_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Merge `fields` into the row with this id. None if no such row."""
    topics = load_topics()
    idx = next((i for i, t in enumerate(topics) if t.get("id") == topic_id), -1)
    if idx < 0:
        return None

    merged = dict(fields)
    if "stage" in merged:
        merged["stage"] = _normalize_stage(merged["stage"])
    topics[idx].update(merged)
    topics[idx]["updated_at"] = datetime.now().isoformat()

    save_topics(topics)
    return topics[idx]


def delete_topic(topic_id: Optional[str] = None, topic: Optional[str] = None) -> int:
    """Remove by id first, else by topic title. Returns the remaining count."""
    topics = load_topics()
    if topic_id:
        topics = [t for t in topics if t.get("id") != topic_id]
    elif topic:
        topics = [t for t in topics if t.get("topic") != topic]

    save_topics(topics)
    return len(topics)


def find_topics(query: str, channel: Optional[str] = None) -> List[Dict[str, Any]]:
    """Case-insensitive substring search over topic/notes/category/channel."""
    q = (query or "").strip().lower()
    chan = (channel or "").strip().lower()

    matches = []
    for t in load_topics():
        if chan and chan not in str(t.get("channel", "")).lower():
            continue
        if not q:
            matches.append(t)
            continue
        haystacks = (
            str(t.get("topic", "")),
            str(t.get("notes", "")),
            str(t.get("category", "")),
            str(t.get("channel", "")),
        )
        if any(q in h.lower() for h in haystacks):
            matches.append(t)
    return matches
