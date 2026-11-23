"""Fit a chat to a context budget (tokens), deterministically.

Order, stopping as soon as the estimate is within the budget:
  (a) cut the system prompt's persistent-memory section;
  (b) collapse old '## Tool results' blocks (oldest first, not the last 2 messages);
  (c) collapse older assistant replies;
  (d) trim the oldest '### Input Asset' blocks in the first user message.
The last user message is never touched.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Tuple

MEMORY_MARKER = "### Persistent Agent Memory Context"
TRIM_NOTE = "[... trimmed to fit the context; the full text was read earlier ...]"
_ASSET_MARKER = "### Input Asset"


def estimate_tokens(system: str, messages: List[Dict[str, str]]) -> int:
    texts = [system or ""] + [str(m.get("content") or "") for m in messages]
    total = sum(len(t) for t in texts)
    dev = sum(1 for t in texts for ch in t if "ऀ" <= ch <= "ॿ")
    cpt = 2.6 if total and dev / total > 0.2 else 3.2
    return math.ceil(total / cpt) + 16 * len(messages)


def fit_messages(system: str, messages: List[Dict[str, str]], budget: int) -> Tuple[str, List[Dict[str, str]]]:
    msgs = [dict(m) for m in messages]
    system = system or ""

    def fits() -> bool:
        return estimate_tokens(system, msgs) <= budget

    if fits():
        return system, msgs

    # (a) memory section
    idx = system.find(MEMORY_MARKER)
    if idx >= 0:
        system = system[:idx].rstrip()
        if fits():
            return system, msgs

    protected = max(0, len(msgs) - 2)
    last_user = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=-1)

    # (b) tool results, oldest first
    for i in range(protected):
        m = msgs[i]
        c = str(m.get("content") or "")
        if m.get("role") == "user" and c.startswith("## Tool results") and i != last_user:
            parts = re.split(r"(?m)^(?=### )", c)
            out = []
            for p in parts:
                if p.startswith("### "):
                    head, _, body = p.partition("\n")
                    if len(body) > 600:
                        p = f"{head}\n{body[:600]}\n{TRIM_NOTE}\n"
                out.append(p)
            m["content"] = "".join(out)
            if fits():
                return system, msgs

    # (c) older assistant replies
    for i in range(protected):
        m = msgs[i]
        c = str(m.get("content") or "")
        if m.get("role") == "assistant" and len(c) > 1500:
            m["content"] = c[:1500] + "\n" + TRIM_NOTE
            if fits():
                return system, msgs

    # (d) input assets in the first user message (oldest first)
    first = next((i for i, m in enumerate(msgs) if m.get("role") == "user"), -1)
    if first >= 0 and first != last_user:
        c = str(msgs[first].get("content") or "")
        parts = re.split(r"(?m)^(?=" + re.escape(_ASSET_MARKER) + ")", c)
        for k, p in enumerate(parts):
            if not p.startswith(_ASSET_MARKER):
                continue
            over = estimate_tokens(system, msgs) - budget
            if over <= 0:
                break
            cut_chars = int(over * 3.2) + 64
            head, _, body = p.partition("\n")
            keep = max(0, len(body) - cut_chars)
            parts[k] = f"{head}\n{body[:keep]}\n{TRIM_NOTE}\n"
            msgs[first]["content"] = "".join(parts)
        msgs[first]["content"] = "".join(parts)
    return system, msgs
