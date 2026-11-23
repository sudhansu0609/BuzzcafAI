"""Google's rate limit on the local Gemini harness: when it hit and when the next window opens.

The harness answers 429 with the time; the Studio keeps it here so calls skip Gemini
(and fall back to the local model) until then, and the pop-up / Health page can say so.
"""
import json
import os
from datetime import datetime
from typing import Optional

from core.paths import KNOWLEDGE_DIR

LIMIT_FILE = os.path.join(KNOWLEDGE_DIR, "usage", "gemini_rate_limit.json")


def _parse(iso: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(iso))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def record(until_iso: str, estimated: bool, message: str) -> dict:
    rec = {"since": datetime.now().astimezone().isoformat(timespec="seconds"),
           "until": until_iso, "estimated": bool(estimated), "message": (message or "")[:300]}
    try:
        os.makedirs(os.path.dirname(LIMIT_FILE), exist_ok=True)
        with open(LIMIT_FILE, "w", encoding="utf-8") as f:
            json.dump(rec, f)
    except OSError:
        pass
    return rec


def active() -> Optional[dict]:
    """The record while its window has not opened yet, else None."""
    try:
        with open(LIMIT_FILE, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    until = _parse(rec.get("until", "")) if isinstance(rec, dict) else None
    if until and until > datetime.now().astimezone():
        return rec
    return None


def clear() -> None:
    try:
        os.remove(LIMIT_FILE)
    except OSError:
        pass
