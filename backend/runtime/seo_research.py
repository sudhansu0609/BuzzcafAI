"""The SEO step as research: demand, competition and virality, then the package.

Until now the SEO step was one call: the model was handed the script and asked
for titles, a description and tags, with no idea what anybody searches for or
what already ranks. Here it researches first, the way the researcher does
(runtime/research_loop.py):

1. **A demand snapshot** is put in front of it before it starts: YouTube's own
   autocomplete for the topic (what people actually type), what ranks for it
   and how those videos do (views, age, views per day), and how this channel's
   own recent uploads did -- so even a model that never calls a tool has
   evidence to work from.
2. **Its tools**: `[YT_SUGGEST: seed]` (autocomplete -- run it on English,
   Hindi and Hinglish seeds), `[YOUTUBE_SEARCH: query]`, `[OWN_CHANNEL]`,
   `[WEB_SEARCH: query]`, `[WEB_FETCH: url]` and `[NEWS_SEARCH: query]` (is the
   subject in the news now?). Results come back as the next turn.
3. **The package** keeps the evidence: the queries with demand, the videos it
   competes with, the gap it fills, a virality score with reasons, the title
   options each with why, thumbnail text, description, tags and hashtags
   (`parse_seo_package` reads the parts the publish files need).

`run()` falls back to one call when no model answers the chat, like the
research loop. It never fails the step on a lookup that fails.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("buzzcaf_ai.engine.seo_research")

MAX_TURNS = 5
MAX_CALLS_PER_TURN = 8
RESULT_CHARS = 8000
SUGGEST_URL = "https://suggestqueries.google.com/complete/search"

_SUGGEST_RE = re.compile(r"\[YT_SUGGEST:\s*(.*?)\](?:\[/YT_SUGGEST\])?", re.IGNORECASE)
_YOUTUBE_RE = re.compile(r"\[YOUTUBE_SEARCH:\s*(.*?)\](?:\[/YOUTUBE_SEARCH\])?", re.IGNORECASE)
_OWN_RE = re.compile(r"\[OWN_CHANNEL(?::[^\]]*)?\]", re.IGNORECASE)

#: Words that put a seed in the channel's niche when the title alone is too narrow.
_NICHE = {
    "Raat3Baje": "horror story hindi",
    "Beyond3Baje": "paranormal story hindi",
    "Life3Baje": "youtuber journey hindi",
    "Khayal3Baje": "horror animation hindi",
}

PACKAGE_SHAPE = """{
  "research": {
    "search_demand": [{"query": "what people type", "evidence": "autocomplete / how many strong videos / views per day"}],
    "competition": [{"title": "...", "channel": "...", "views": 0, "views_per_day": 0, "url": "..."}],
    "gap": "what the ranking videos miss that this video has",
    "trend": "a timely angle, if the subject is in the news or rising (else empty)",
    "audience_questions": ["questions viewers ask about this subject"],
    "virality": {"score": 0, "why": "demand x curiosity x competition x fit for this channel", "risks": "..."}
  },
  "primary_keyword": "...",
  "secondary_keywords": ["..."],
  "titles": [{"title": "<= 70 characters", "why": "which demand or curiosity it hits"}],
  "thumbnail_text": ["2-4 words", "..."],
  "thumbnail_concept": "one clear subject, what the eye lands on",
  "description": "first two lines = hook + primary keyword; then what the video is, chapters if useful, secondary keywords naturally",
  "tags": ["broad", "specific", "long-tail", "Hindi/Hinglish variants"],
  "hashtags": ["#..."],
  "pinned_comment": "a question that starts the comments"
}"""

TOOL_GUIDE = """
### How you research the SEO (tools you can call)
Write tool tags in your reply, each on its own line. They are run for you and the results come back in
the next message. Nothing else you write in that reply is kept.
- `[YT_SUGGEST: seed]` -- YouTube's autocomplete for a seed: what people actually type. Run it on 3-6
  seeds: the subject in English, in Hindi (Devanagari) and in Hinglish, and the entity/place/person alone.
- `[YOUTUBE_SEARCH: query]` -- what ranks for a query: titles, channels, views, age, views per day.
- `[OWN_CHANNEL]` -- this channel's recent uploads and how each did.
- `[WEB_SEARCH: query]` / `[WEB_FETCH: url]` -- the web; `[NEWS_SEARCH: query]` -- is it in the news now?
Up to {calls} tool calls per reply, up to {turns} replies.

Research FIRST: your first reply is tool calls only. Find (1) the queries with real demand -- the ones
autocomplete offers and strong videos answer; (2) the competition -- the top videos, how big and how old,
views per day; (3) the gap -- what they miss that this video has; (4) whether there is a timely angle.
Then score virality honestly (0-100: demand x curiosity x low competition x fit for this channel's
audience) and write titles that hit the demand you found without lying about the video.
When you have enough, reply with ONLY the JSON package below -- no tags, no prose:
{shape}
Rules: 5 title options, each <= 70 characters, curiosity without clickbait the video does not pay off,
in the channel's language mix (Hinglish/Hindi/English as its guide says). Tags: 15-30, broad to
long-tail, with Hindi and Hinglish variants, under 500 characters in all. 3-6 hashtags. Base every
claim in "research" on what the tools showed you; leave a part empty rather than invent numbers.
"""


# --- the lookups ----------------------------------------------------------------------------

def suggest(seed: str, limit: int = 10) -> List[str]:
    """YouTube autocomplete for `seed` (Google's suggest endpoint, `ds=yt`); [] on any failure."""
    seed = (seed or "").strip()
    if not seed:
        return []
    try:
        resp = requests.get(SUGGEST_URL, params={"client": "firefox", "ds": "yt", "q": seed, "hl": "hi"},
                            timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = json.loads(resp.content.decode("utf-8", "ignore"))
    except Exception as exc:  # noqa: BLE001 - no signal is not an error
        logger.info("YouTube autocomplete failed for %r: %s", seed, exc)
        return []
    items = data[1] if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list) else []
    return [str(s) for s in items if str(s).strip()][:limit]


def suggest_text(seed: str) -> str:
    rows = suggest(seed)
    if not rows:
        return f"No autocomplete for '{seed}' (nobody types it, or the lookup is unavailable)."
    return f"YouTube autocomplete for '{seed}':\n" + "\n".join(f"- {r}" for r in rows)


def own_channel_text(brand: str, limit: int = 15) -> str:
    """This brand's recent uploads with their views, from its YouTube channel."""
    try:
        from integrations.youtube_publish import channel_for_brand
        from app.services.video_intel import fetch_channel_videos
        channel_id = channel_for_brand(brand)
        if not channel_id:
            return f"No YouTube channel is linked to {brand} in the Studio."
        videos = fetch_channel_videos(f"https://www.youtube.com/channel/{channel_id}", limit=limit)
    except Exception as exc:  # noqa: BLE001
        return f"The channel's uploads could not be read: {exc}"
    if not videos:
        return f"{brand}'s channel has no uploads to read."
    lines = [f"{brand}'s recent uploads (newest first):"]
    lines += [f"- {v['title']} -- {v['view_count']:,} views" + (f", {v['duration'] // 60} min" if v.get("duration") else "")
              for v in videos]
    return "\n".join(lines)


def _seeds(project: Any) -> List[str]:
    from app.services.writing_style import canonical_channel
    name = re.sub(r"\s+", " ", str(getattr(project, "name", "") or "")).strip()
    seeds = [name]
    words = name.split()
    if len(words) > 4:
        seeds.append(" ".join(words[:4]))
    niche = _NICHE.get(canonical_channel(getattr(project, "brand", "")))
    if niche:
        seeds.append(f"{' '.join(words[:3])} {niche}".strip())
    return [s for s in dict.fromkeys(seeds) if s]


def demand_snapshot(project: Any) -> str:
    """What the SEO agent sees before it starts: autocomplete for the topic,
    what ranks for it, and the channel's own recent uploads."""
    from runtime.research_loop import youtube_results
    parts: List[str] = []
    seeds = _seeds(project)
    for seed in seeds[:3]:
        rows = suggest(seed)
        if rows:
            parts.append(f"Autocomplete for '{seed}': " + " | ".join(rows))
    try:
        parts.append(youtube_results(seeds[0], limit=8))
    except Exception as exc:  # noqa: BLE001
        logger.info("SEO snapshot: YouTube search failed: %s", exc)
    own = own_channel_text(getattr(project, "brand", ""), limit=10)
    if own:
        parts.append(own)
    if not parts:
        return ""
    return "\n\n### Demand snapshot (fetched just now -- a first look; your own lookups decide)\n" + "\n\n".join(parts) + "\n"


def _collect(reply: str, brand: str) -> List[Tuple[int, str, Callable[[], str]]]:
    from app.services import studio_chat as sc
    from runtime.research_loop import youtube_results

    found: List[Tuple[int, str, Callable[[], str]]] = []
    for m in _SUGGEST_RE.finditer(reply):
        q = m.group(1).strip()
        found.append((m.start(), f"autocomplete: {q[:100]}", (lambda q=q: suggest_text(q))))
    for m in _YOUTUBE_RE.finditer(reply):
        q = m.group(1).strip()
        found.append((m.start(), f"youtube search: {q[:100]}", (lambda q=q: youtube_results(q))))
    for m in _OWN_RE.finditer(reply):
        found.append((m.start(), "own channel", (lambda: own_channel_text(brand))))
    for regex, name in ((sc._SEARCH_RE, "web search"), (sc._FETCH_RE, "fetch"), (sc._NEWS_RE, "news search")):
        for m in regex.finditer(reply):
            label = f"{name}: {m.group(1).strip()[:100]}"
            found.append((m.start(), label, (lambda m=m: sc.process_web_research_tags(
                m.group(0), max_results=6, fetch_chars=4000, per_source=4))))
    found.sort(key=lambda f: f[0])
    return found


def parse_package(text: str) -> Optional[Dict[str, Any]]:
    """The package in a reply, or None: JSON with titles and tags or a description."""
    from integrations.youtube_publish import parse_seo_package
    if not parse_seo_package(text):
        return None
    from integrations.llm import clean_json_response
    try:
        data = json.loads(clean_json_response(str(text)), strict=False)
    except ValueError:
        return {"raw": text}
    return data if isinstance(data, dict) else {"raw": text}


class _NoModel(Exception):
    pass


def run(agent, project: Any, task: str, log: Callable[[str], None], *, max_turns: int = MAX_TURNS) -> Dict[str, Any]:
    """Research, then the package. Returns {"raw", "package", "calls", "turns"}."""
    llm = agent.llm_service
    try:
        snapshot = demand_snapshot(project)
    except Exception as exc:  # noqa: BLE001 - the loop works without it
        logger.warning("SEO snapshot failed: %s", exc)
        snapshot = ""
    if snapshot:
        log("SEO research: demand snapshot added (autocomplete, ranking videos, the channel's uploads).")
    full_task = task + snapshot
    if hasattr(llm, "generate_chat"):
        try:
            return _loop(agent, llm, project, full_task, log, max_turns)
        except _NoModel:
            logger.warning("SEO research: no model answered the chat; falling back to one call.")
    raw = str(agent.execute(full_task + "\n\nReply with ONLY the JSON package:\n" + PACKAGE_SHAPE,
                            require_json=True) or "")
    return {"raw": raw, "package": parse_package(raw), "calls": [], "turns": 1}


def _loop(agent, llm, project: Any, task: str, log: Callable[[str], None], max_turns: int) -> Dict[str, Any]:
    try:
        agent.refresh_prompt()
    except Exception:
        pass
    system = getattr(agent, "system_prompt", "") or ""
    guide = TOOL_GUIDE.format(calls=MAX_CALLS_PER_TURN, turns=max_turns, shape=PACKAGE_SHAPE)
    messages: List[Dict[str, str]] = [{"role": "user", "content": task + guide}]
    calls_made: List[str] = []
    nudged = False
    for turn in range(1, max_turns + 2):
        # Master pause (docs/STUDIO_DIRECTOR_PLAN.md Part 1): between turns,
        # before the next model call.
        from app.services import master_control
        master_control.wait_if_paused(f"seo_research: turn {turn}", log)
        last_chance = turn > max_turns
        if last_chance:
            messages[-1]["content"] += "\n\nStop researching now. Reply with ONLY the JSON package from what you have."
        reply = str(llm.generate_chat(system_prompt=system, messages=messages,
                                      tier=getattr(agent, "model_tier", None),
                                      temperature=getattr(agent, "temperature", None)) or "")
        if getattr(llm, "last_response_simulated", False):
            raise _NoModel()
        if not reply.strip():
            raise RuntimeError("the SEO manager returned an empty reply")
        calls = _collect(reply, getattr(project, "brand", ""))
        package = parse_package(reply) if not calls else None
        if package is not None:
            if not calls_made and not nudged and not last_chance:
                nudged = True
                log("SEO research: the package was written without a single lookup; sent back to research first.")
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": (
                    "Not yet: that is a guess, not research. Reply with tool calls only -- [YT_SUGGEST: ...] on "
                    "English, Hindi and Hinglish seeds and [YOUTUBE_SEARCH: ...] for the top queries -- then the package.")})
                continue
            log(f"SEO research: package written after {turn} turn(s), {len(calls_made)} lookup(s).")
            return {"raw": reply, "package": package, "calls": calls_made, "turns": turn}
        if last_chance:
            log(f"SEO research: no JSON package after {max_turns} turns; the reply is kept as it is.")
            return {"raw": reply, "package": None, "calls": calls_made, "turns": turn}
        messages.append({"role": "assistant", "content": reply})
        if not calls:
            messages.append({"role": "user", "content": (
                "You neither called a tool nor wrote the JSON package. Call the tools you need, or reply with ONLY "
                "the JSON package if you have enough.")})
            continue
        results = []
        for i, (_, label, fn) in enumerate(calls):
            if i >= MAX_CALLS_PER_TURN:
                results.append(f"### {label}\nNot run: at most {MAX_CALLS_PER_TURN} tool calls per reply.")
                continue
            log(f"SEO research: {label}")
            calls_made.append(label)
            try:
                out = str(fn()).strip()
            except Exception as exc:  # noqa: BLE001 - reported back to the agent
                out = f"failed: {exc}"
            results.append(f"### {label}\n{out[:RESULT_CHARS]}")
        messages.append({"role": "user", "content": (
            "## Tool results (" + datetime.now().strftime("%Y-%m-%d") + ")\n\n" + "\n\n".join(results)
            + "\n\nContinue researching what is still unclear, otherwise reply with ONLY the JSON package.")})
    raise RuntimeError(f"the SEO manager did not answer in {max_turns} turns")  # not reached
