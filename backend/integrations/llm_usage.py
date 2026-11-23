"""One line per model call: which model answered which job, how long it took
and how many tokens it used (2026-10-26). `knowledge/usage/llm_calls.jsonl`.

The tokens are the server's own count when it gives one (the Claude proxy,
LM Studio, Ollama) and an estimate otherwise (the Gemini harness says nothing);
`estimated` marks which. The seconds are the whole call, including providers
that failed first, because that is what a step actually waits.

This is what the forecasts (`app/services/run_forecast.py`) and the Model
Routing window's token figures are built from.
"""
import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.llm_usage")

USAGE_DIR = os.path.join(KNOWLEDGE_DIR, "usage")
CALLS_PATH = os.path.join(USAGE_DIR, "llm_calls.jsonl")
_LOCK = threading.Lock()
# A file past this is rotated to llm_calls.<date>.jsonl, so reads stay quick.
_MAX_BYTES = 20 * 1024 * 1024


def record(*, provider: Optional[str], model: str, job: Optional[str], tier: Optional[str],
           prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0,
           estimated: bool, seconds: float, ok: bool, step: str = "") -> None:
    row = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "provider": provider or "", "model": model or "", "job": job or "", "tier": tier or "",
        "step": step or "",
        "in": int(prompt_tokens), "out": int(completion_tokens), "cached": int(cached_tokens),
        "estimated": bool(estimated), "s": round(float(seconds), 1), "ok": bool(ok),
    }
    try:
        with _LOCK:
            os.makedirs(USAGE_DIR, exist_ok=True)
            if os.path.exists(CALLS_PATH) and os.path.getsize(CALLS_PATH) > _MAX_BYTES:
                os.replace(CALLS_PATH, os.path.join(USAGE_DIR, f"llm_calls.{datetime.now():%Y%m%d%H%M%S}.jsonl"))
            with open(CALLS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    except OSError as exc:
        logger.debug("Could not record model usage: %s", exc)


def calls(days: float = 7.0) -> List[Dict[str, Any]]:
    """The recorded calls of the last `days` days, oldest first."""
    if not os.path.exists(CALLS_PATH):
        return []
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    out = []
    with open(CALLS_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("at", "") >= since:
                out.append(row)
    return out


def summary(days: float = 7.0) -> Dict[str, Any]:
    """Per job and provider: calls, average tokens and seconds per call, and
    per-day totals for Claude (whose allowance is shared with the creator)."""
    rows = calls(days)
    groups: Dict[tuple, Dict[str, Any]] = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "s": 0.0,
                                                              "failed": 0, "estimated": 0})
    claude_days: Dict[str, Dict[str, int]] = defaultdict(lambda: {"in": 0, "out": 0, "calls": 0})
    for r in rows:
        g = groups[(r.get("job") or "", r.get("provider") or "")]
        g["calls"] += 1
        g["in"] += r.get("in", 0)
        g["out"] += r.get("out", 0)
        g["s"] += r.get("s", 0.0)
        g["failed"] += 0 if r.get("ok") else 1
        g["estimated"] += 1 if r.get("estimated") else 0
        if r.get("provider") == "claude":
            d = claude_days[r["at"][:10]]
            d["in"] += r.get("in", 0)
            d["out"] += r.get("out", 0)
            d["calls"] += 1
    by_job = []
    for (job, provider), g in sorted(groups.items()):
        n = max(1, g["calls"])
        by_job.append({"job": job or "other", "provider": provider or "none", "calls": g["calls"],
                       "failed": g["failed"], "avg_in": g["in"] // n, "avg_out": g["out"] // n,
                       "avg_s": round(g["s"] / n, 1), "total_in": g["in"], "total_out": g["out"],
                       "estimated_share": round(g["estimated"] / n, 2)})
    return {"days": days, "calls": len(rows), "by_job": by_job,
            "claude_per_day": [{"date": d, **v} for d, v in sorted(claude_days.items())]}


def averages(days: float = 14.0) -> Dict[str, Dict[str, Dict[str, float]]]:
    """{job: {provider: {in, out, s, calls}}} per successful call -- for forecasts."""
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for row in summary(days)["by_job"]:
        if row["calls"] - row["failed"] <= 0 or row["provider"] == "none":
            continue
        out.setdefault(row["job"], {})[row["provider"]] = {
            "in": row["avg_in"], "out": row["avg_out"], "s": row["avg_s"], "calls": row["calls"]}
    return out
