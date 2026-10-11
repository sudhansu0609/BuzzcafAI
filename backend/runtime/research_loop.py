"""The research step as a tool loop: search, read, search again, then write.

Until now a research step was one call. The agent was handed four snippets
from a single search of the project's title (a Hinglish story title, which
no search engine understands) and asked for a JSON dossier; with
`require_json` set, the one research round `BaseAgent` offers was skipped
too, so the `[WEB_SEARCH]` tags its persona tells it to use were never run.
The "research" that came back was what the model remembered -- or, from a
small local model, nothing at all.

Here the researcher works the way the unattended strategist does
(`app/services/strategist_runner.py`): every reply may carry tool tags
(`[WEB_SEARCH: ...]`, `[WEB_FETCH: url]`, `[BOOK_SEARCH]`, `[NEWS_SEARCH]`,
`[ARCHIVE_SEARCH]`), the tags are run, the results come back as the next user
turn, and the loop ends when the reply is the JSON dossier. A reply that
writes the dossier without having searched is sent back once: search first.
A reply with nothing in it is treated as a failed call.

`run()` returns the dossier (a dict), the JSON text to store, and the list of
tool calls made, for the step log. It raises RuntimeError when no model
answers or no dossier comes back, so the step fails visibly instead of
completing with empty research.
"""

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("buzzcaf_ai.engine.research_loop")

MAX_TURNS = 5
MAX_CALLS_PER_TURN = 6
RESULT_CHARS = 7000
DOSSIER_KEYS = ("timeline", "facts", "sources", "media", "unanswered_questions", "story_material")

TOOL_GUIDE = """
### How you research (tools you can call)
Write tool tags in your reply, each on its own line. They are run for you and the results come back
in the next message. Nothing else you write in that reply is kept.
- `[WEB_SEARCH: query]` -- live web search, a few results with snippets. Queries in ENGLISH find the
  most (a Hinglish title finds nothing); add a query or two with the Hindi/regional words for folklore
  terms, entity names and places.
- `[WEB_FETCH: url]` -- the readable text of one page from a result. Fetch the two or three most
  promising pages: snippets are not research.
- `[BOOK_SEARCH: query]`, `[NEWS_SEARCH: query]`, `[ARCHIVE_SEARCH: query]` -- books, news and archives.
Up to {calls} tool calls per reply, up to {turns} replies.

Search FIRST, write SECOND. Your first reply is tool calls only: at least three different searches
from different angles (the event or legend itself; the place, the job or the setting; the folklore
entity or belief; what has been reported or written about it). Read the results, fetch the best
pages, search again for what is still missing, then write.
When you have enough, reply with ONLY the JSON dossier the task describes -- no tags, no prose.
"""

_PARSE_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_dossier(text: str) -> Optional[Dict[str, Any]]:
    """The JSON dossier in a reply, or None: a dict with at least one known key."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rsplit("```", 1)[0]
    m = _PARSE_RE.search(s)
    if not m:
        return None
    try:
        data = json.loads(m.group(0), strict=False)
    except ValueError:
        return None
    if not isinstance(data, dict) or not any(k in data for k in DOSSIER_KEYS):
        return None
    return data


def _collect(reply: str) -> List[Tuple[int, str, Callable[[], str]]]:
    """The tool tags in a reply, in order, each with a label and a runner."""
    from app.services import studio_chat as sc

    found: List[Tuple[int, str, Callable[[], str]]] = []
    for regex, name in ((sc._SEARCH_RE, "web search"), (sc._FETCH_RE, "fetch"), (sc._BOOK_RE, "book search"),
                        (sc._NEWS_RE, "news search"), (sc._ARCHIVE_RE, "archive search")):
        for m in regex.finditer(reply):
            label = f"{name}: {m.group(1).strip()[:120]}"
            found.append((m.start(), label, (lambda m=m: sc.process_web_research_tags(m.group(0)))))
    found.sort(key=lambda f: f[0])
    return found


def _count_items(dossier: Dict[str, Any]) -> int:
    n = 0
    for key in DOSSIER_KEYS:
        value = dossier.get(key)
        if isinstance(value, list):
            n += len(value)
        elif isinstance(value, dict):
            n += sum(len(v) if isinstance(v, list) else 1 for v in value.values())
        elif value:
            n += 1
    return n


class _NoModel(Exception):
    """No provider answered the chat (the canned fixture did): the step falls
    back to the single call, which labels its reply simulated as before."""


def run(agent, task: str, log: Callable[[str], None], *, max_turns: int = MAX_TURNS) -> Dict[str, Any]:
    """Loop the researcher over its tools until it writes the dossier.

    Returns {"dossier": dict or None, "raw": text to store, "calls": [labels],
    "turns": n, "simulated": bool}. Raises RuntimeError when the model answers
    but never delivers a dossier, or answers with nothing."""
    llm = agent.llm_service
    if hasattr(llm, "generate_chat"):
        try:
            return _loop(agent, llm, task, log, max_turns)
        except _NoModel:
            logger.warning("Research loop: no model answered the chat; falling back to one call.")
    # A service without multi-turn chat (a test double), or no provider for
    # the loop: the single call as before, labelled simulated when it is.
    raw = str(agent.execute(task, require_json=True) or "")
    simulated = bool(getattr(llm, "last_response_simulated", False))
    if not raw.strip() and not simulated:
        raise RuntimeError("the researcher returned an empty reply")
    return {"dossier": _parse_dossier(raw), "raw": raw, "calls": [], "turns": 1, "simulated": simulated}


def _loop(agent, llm, task: str, log: Callable[[str], None], max_turns: int) -> Dict[str, Any]:
    try:
        agent.refresh_prompt()
    except Exception:
        pass
    system = getattr(agent, "system_prompt", "") or ""
    guide = TOOL_GUIDE.format(calls=MAX_CALLS_PER_TURN, turns=max_turns)
    messages: List[Dict[str, str]] = [{"role": "user", "content": task + guide}]
    calls_made: List[str] = []
    nudged_memory = False

    for turn in range(1, max_turns + 2):
        last_chance = turn > max_turns
        if last_chance:
            messages[-1]["content"] += ("\n\nStop researching now. Reply with ONLY the JSON dossier, "
                                        "from what you have, citing the URLs you read.")
        reply = str(llm.generate_chat(system_prompt=system, messages=messages,
                                      tier=getattr(agent, "model_tier", None),
                                      temperature=getattr(agent, "temperature", None)) or "")
        if getattr(llm, "last_response_simulated", False):
            raise _NoModel()
        if not reply.strip():
            raise RuntimeError("the researcher returned an empty reply")
        calls = _collect(reply)
        dossier = _parse_dossier(reply)
        if dossier is not None and not calls:
            if not calls_made and not nudged_memory and not last_chance:
                # Written from memory: send it back once to look things up.
                nudged_memory = True
                log("Research: the dossier was written without a single search; sent back to search first.")
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": (
                    "Not yet. That dossier comes from memory, and memory is not research. Reply with tool calls "
                    "only -- at least three different [WEB_SEARCH: ...] queries in English (plus one with the "
                    "Hindi/regional words) -- and write the dossier only after reading the results.")})
                continue
            log(f"Research: dossier written after {turn} turn(s), {len(calls_made)} tool call(s), "
                f"{_count_items(dossier)} items.")
            return {"dossier": dossier, "raw": json.dumps(dossier, ensure_ascii=False, indent=2),
                    "calls": calls_made, "turns": turn, "simulated": False}
        if last_chance:
            # Prose to the end: kept verbatim and labelled, never faked into
            # sections (the engine records every section as missing).
            log(f"Research: no JSON dossier after {max_turns} turns; the reply is kept as prose.")
            return {"dossier": None, "raw": reply, "calls": calls_made, "turns": turn, "simulated": False}
        messages.append({"role": "assistant", "content": reply})
        if not calls:
            messages.append({"role": "user", "content": (
                "You neither called a tool nor wrote the JSON dossier. Write the tool calls you need "
                "([WEB_SEARCH: ...] / [WEB_FETCH: url] ...), or ONLY the JSON dossier if you have enough.")})
            continue
        results = []
        for i, (_, label, fn) in enumerate(calls):
            if i >= MAX_CALLS_PER_TURN:
                results.append(f"### {label}\nNot run: at most {MAX_CALLS_PER_TURN} tool calls per reply.")
                continue
            log(f"Research: {label}")
            calls_made.append(label)
            try:
                out = str(fn()).strip()
            except Exception as exc:  # noqa: BLE001 - reported back to the researcher
                logger.warning("research tool '%s' failed: %s", label, exc)
                out = f"failed: {exc}"
            results.append(f"### {label}\n{out[:RESULT_CHARS]}")
        messages.append({"role": "user", "content": (
            "## Tool results\n\n" + "\n\n".join(results)
            + "\n\nContinue: fetch the best pages and search for what is still missing, otherwise reply with "
              "ONLY the JSON dossier (cite the URLs you actually read).")})
    raise RuntimeError(f"the researcher did not answer in {max_turns} turns")  # not reached: the last turn returns
