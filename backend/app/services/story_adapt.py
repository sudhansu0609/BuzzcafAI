"""A Story Library entry adapted into a Raat3Baje script in the creator's own
voice (AUTO_STORY_PLAN.md, brief L2).

`adapt(entry_id, parts=, minutes_per_part=)` creates a project on the
`raat3baje_adaptation` workflow, writes the source text to
`research/source_story.md` (asset `source_story`, read by the Adaptation step)
and puts the parts, minutes and rights in `metadata.adaptation` and the
creator's instructions. Rights decide what the StoryAdapter may do: a
`public_domain` story is retold freely; a `protected` one is refused unless
`inspired=True`, and then (as for `unknown`) only an original story built on
its premise is written (`metadata.adaptation.mode = "inspired"`).

A collection (one entry, many stories) is split with `split_collection` and
only one story is adapted (`story_index` / `story_title`, else the longest
under 12,000 words; `metadata.adaptation.story_title`). The Adaptation step
runs once per part (`adapt_in_parts`) on that part's section of the story,
never through runtime/long_script.py, and the parts are joined into
script/script.md under `# Part k` headings.

With `run=True` the steps run in a background job with approvals bypassed,
the way the nightly long-form build runs pre-production, and stop before the
Visual Plan for the creator's review. Before Human Touch the machine-writing
report (`writing_style.ai_tells`) of the adaptation is written to
`script/ai_tells.md` (asset `ai_tells`); after it, the final script is scored
into `metadata.human_score`, and above `HUMAN_RETRY_ABOVE` Human Touch runs
once more on its own output (at most `HUMAN_MAX_PASSES` passes; a second pass
that scores worse is undone).
"""
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("buzzcaf_ai.story_adapt")

WORKFLOW = "raat3baje_adaptation"
DEFAULT_CHANNEL = "Raat3Baje"
ADAPT_STEP = "Adaptation"
HUMAN_STEP = "Human Touch"
STOP_STEP = "Visual Plan"   # no longer a stop (creator 2026-10-24: "let's not wait on the visual plan")
#: The adaptation runs through the Visual Plan and SEO steps to the end of the workflow.
DONE_STEPS = ("Completed",)
MAX_STEPS = 10

SOURCE_ASSET = "source_story"
SOURCE_REL = "research/source_story.md"
SOURCE_FULL_ASSET = "source_full"
SOURCE_FULL_REL = "research/source_full.md"
SCRIPT_REL = "script/script.md"
TELLS_ASSET = "ai_tells"
TELLS_REL = "script/ai_tells.md"

HUMAN_RETRY_ABOVE = 40
HUMAN_MAX_PASSES = 2

RIGHTS = ("public_domain", "protected", "unknown")
MAX_PARTS = 10


class AdaptError(ValueError):
    """The entry cannot be adapted as asked (missing, empty, or protected)."""


# --- the library entry ---------------------------------------------------------------

def _library_dir(entry_id: str) -> str:
    from core import paths
    return os.path.join(str(paths.KNOWLEDGE_DIR), "stories", "library", entry_id)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def load_entry(entry_id: str) -> Tuple[Dict[str, Any], str]:
    """(meta, full text) of a library entry: through app/services/story_library
    when it is there, else straight from knowledge/stories/library/<id>/."""
    meta: Optional[Dict[str, Any]] = None
    try:
        from app.services import story_library  # built by brief L1
        found = story_library.entry(entry_id)
        if isinstance(found, dict):
            meta = found
    except ImportError:
        pass
    if meta is None:
        raw = _read(os.path.join(_library_dir(entry_id), "meta.json"))
        try:
            meta = json.loads(raw) if raw else None
        except ValueError:
            meta = None
    if not meta:
        raise AdaptError(f"Story Library entry '{entry_id}' was not found.")
    text = str(meta.get("text") or "") or _read(os.path.join(_library_dir(entry_id), "story.txt"))
    if not text.strip():
        raise AdaptError(f"Story Library entry '{entry_id}' has no text (story.txt is missing or empty).")
    return meta, text


# --- a collection, split into its stories ---------------------------------------------

MIN_STORY_WORDS = 800
DEFAULT_PIECE_MAX_WORDS = 12000

_SMALL_WORDS = frozenset("a an and as at but by for from in into nor of on or the to with".split())
_NUMBERING_RE = re.compile(r"^(?:CHAPTER|Chapter)\b[\w .:-]*$|^[IVXLC]+\.?$")
_TITLE_WORD_RE = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)


def _words(text: str) -> int:
    return len((text or "").split())


def _heading_kind(line: str) -> Optional[str]:
    """'title' (an ALL-CAPS or Title-Case line), 'number' (CHAPTER / Chapter N /
    a roman numeral) or None. The blank lines around it are checked by the caller."""
    s = line.strip()
    if s and s[0] in "\"“'‘" and s[-1] in "\"”'’":       # “OH, WHISTLE, AND I’LL COME TO YOU, MY LAD”
        inner = s[1:-1].strip()
        return "title" if inner and _heading_kind(inner) == "title" and inner.upper() == inner else None
    if not s or len(s) >= 80 or s[-1] in ".,;:!?" or s[0] in "\"“'‘(-*[":
        return None
    if _NUMBERING_RE.match(s):
        return "number"
    words = _TITLE_WORD_RE.findall(s)
    if not words or not any(c.isalpha() and c.isascii() for c in s):
        return None
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return "title"
    if all(w[0].isupper() or w.lower() in _SMALL_WORDS for w in words) and words[0][0].isupper():
        return "title"
    return None


_CONTENTS_RE = re.compile(r"^\s*(?:table of )?contents\.?\s*$", re.IGNORECASE)


def _norm_title(line: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (line or "").lower()).split())


def _contents_starts(lines: List[str]) -> List[int]:
    """When the book has a contents list, the story headings are the lines
    (on their own, between blank lines) that repeat its entries -- so a
    heading-like line inside a story (an inscription, a letter's address)
    does not split it. [] when there is no usable list."""
    at = next((i for i, l in enumerate(lines[:600]) if _CONTENTS_RE.match(l)), None)
    if at is None:
        return []
    entries, i = [], at + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines) and lines[i].strip() and len(entries) < 200:
        entries.append(_norm_title(lines[i]))
        i += 1
    wanted = {e for e in entries if e}
    if len(wanted) < 2:
        return []
    starts, seen = [], set()
    for k in range(i, len(lines)):
        norm = _norm_title(lines[k])
        if (norm in wanted and norm not in seen and len(lines[k].strip()) < 80
                and (k == 0 or not lines[k - 1].strip()) and (k == len(lines) - 1 or not lines[k + 1].strip())):
            starts.append(k)
            seen.add(norm)
    return starts if len(starts) >= 2 else []


def split_collection(text: str) -> List[Dict[str, Any]]:
    """The stories of a collection: [{title, text, words}], split at
    Gutenberg-style headings (a line on its own between blank lines, under 80
    characters, not ending in a period: ALL-CAPS or Title-Case; CHAPTER /
    Chapter N / roman numerals only when the text has no title headings, so a
    story's numbered sections stay in it). A piece under `MIN_STORY_WORDS`
    joins the one before it; a short front (preface, contents) is dropped.
    One piece (title '') when nothing splits."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    marks: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        before = i == 0 or not lines[i - 1].strip()
        after = i == len(lines) - 1 or not lines[i + 1].strip()
        kind = _heading_kind(line) if before and after else None
        if kind:
            marks.append((i, kind))
    titles = [i for i, kind in marks if kind == "title"]
    starts = _contents_starts(lines) or titles or [i for i, kind in marks if kind == "number"]
    whole = [{"title": "", "text": (text or "").strip(), "words": _words(text)}]
    if not starts:
        return whole
    segments: List[Dict[str, Any]] = []
    front = "\n".join(lines[:starts[0]]).strip()
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        body = "\n".join(lines[start + 1:end]).strip()
        segments.append({"title": lines[start].strip().strip("\"“”'‘’ "), "body": body})
    pieces: List[Dict[str, Any]] = []
    for seg in segments:
        if _words(seg["body"]) < MIN_STORY_WORDS and pieces:
            pieces[-1]["text"] += f"\n\n{seg['title']}\n\n{seg['body']}".rstrip()
        elif _words(seg["body"]) < MIN_STORY_WORDS:
            front += f"\n\n{seg['title']}\n\n{seg['body']}"     # contents lines before the first story
        else:
            pieces.append({"title": seg["title"], "text": seg["body"]})
    if not pieces:
        return whole
    for p in pieces:
        p["text"] = p["text"].strip()
        p["words"] = _words(p["text"])
    return pieces


def default_piece(pieces: List[Dict[str, Any]]) -> int:
    """The longest piece under DEFAULT_PIECE_MAX_WORDS, else the shortest."""
    under = [i for i, p in enumerate(pieces) if p["words"] < DEFAULT_PIECE_MAX_WORDS]
    if under:
        return max(under, key=lambda i: pieces[i]["words"])
    return min(range(len(pieces)), key=lambda i: pieces[i]["words"])


def choose_piece(pieces: List[Dict[str, Any]], story_title: Optional[str] = None,
                 story_index: Optional[int] = None) -> int:
    if story_index is not None:
        if not 0 <= int(story_index) < len(pieces):
            raise AdaptError(f"story_index {story_index} is out of range (0-{len(pieces) - 1}).")
        return int(story_index)
    if story_title:
        want = story_title.strip().lower()
        for exact in (True, False):
            for i, p in enumerate(pieces):
                have = p["title"].strip().lower()
                if (have == want) if exact else (want in have):
                    return i
        raise AdaptError(f"No story titled '{story_title}' in this collection.")
    return default_piece(pieces)


def pieces(entry_id: str) -> Dict[str, Any]:
    """An entry's stories, for the page to offer the choice."""
    meta, text = load_entry(entry_id)
    found = split_collection(text)
    return {"entry_id": entry_id, "title": meta.get("title"),
            "pieces": [{"index": i, "title": p["title"] or meta.get("title"), "words": p["words"]}
                       for i, p in enumerate(found)],
            "default": default_piece(found)}


# --- a story, split into its parts ----------------------------------------------------

def chunk_paragraphs(text: str, parts: int) -> List[str]:
    """`parts` chunks of roughly equal words, cut only between paragraphs
    (fewer when there are fewer paragraphs)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    parts = max(1, min(int(parts or 1), len(paras) or 1))
    if parts == 1:
        return ["\n\n".join(paras)]
    sizes = [_words(p) for p in paras]
    total = sum(sizes)
    cum, run = [], 0
    for s in sizes:
        run += s
        cum.append(run)
    cuts, prev = [], -1
    for k in range(1, parts):
        target = total * k / parts
        lo, hi = prev + 1, len(paras) - (parts - k) - 1      # leave a paragraph for every part after
        best = min(range(lo, hi + 1), key=lambda i: (abs(cum[i] - target), i))
        cuts.append(best)
        prev = best
    chunks, start = [], 0
    for cut in cuts + [len(paras) - 1]:
        chunks.append("\n\n".join(paras[start:cut + 1]))
        start = cut + 1
    return chunks


def _running_summary(previous: str) -> str:
    """The parts adapted so far, without a model: the previous part's first
    and last 60 spoken words."""
    from app.services import writing_style
    words = writing_style.narration_text(previous or "").split()
    if len(words) <= 120:
        return " ".join(words)
    return " ".join(words[:60]) + " ... " + " ".join(words[-60:])


def _last_lines(previous: str, n: int = 3) -> str:
    lines = [l for l in (previous or "").splitlines() if l.strip() and not l.lstrip().startswith("#")]
    return "\n".join(lines[-n:])


def _part_source(a: Dict[str, Any], chunk: str, k: int, n: int, previous: Optional[str]) -> str:
    head = [f"# {a.get('story_title') or a.get('title') or 'Untitled'}", "",
            f"Author: {a.get('author') or 'unknown'}", f"Rights: {a.get('rights')}",
            f"Part {k} of {n}", "",
            f"Write ONLY Part {k} of {n}, from this section of the source, under the heading `# Part {k}`."]
    if k == 1:
        head.append("Open with the greeting." + (" End on a cliff." if n > 1 else ""))
    else:
        head.append("No greeting: open with a two-line recap in his voice, then straight back into the story."
                    + (" End on a cliff." if k < n else " This part ends the story."))
    if previous:
        head += ["", "## The story so far (the parts already adapted)", _running_summary(previous),
                 "", "## Where the previous part ended (its last three lines, verbatim)", _last_lines(previous)]
    return "\n".join(head) + "\n\n---\n\n" + chunk.strip() + "\n"


_PART_HEADING_RE = re.compile(r"^\s*#{1,6}\s*part\s+\d+\b.*$", re.IGNORECASE | re.MULTILINE)


def join_parts(outputs: List[str]) -> str:
    """The parts as one script under `# Part k` headings; the greeting kept
    once, in Part 1."""
    from app.services import writing_style
    blocks = []
    for k, text in enumerate(outputs, 1):
        body = _PART_HEADING_RE.sub("", text or "")
        if k > 1:
            body = "\n".join(l for l in body.splitlines() if not l.strip().lower().startswith("[inspired-by:"))
        blocks.append(f"# Part {k}\n\n{body.strip()}\n")
    joined = "\n".join(blocks)
    joined, _ = writing_style.strip_repeated_intro(joined, keep_first=True)
    return re.sub(r"\n{3,}", "\n\n", joined)


def rights_of(meta: Dict[str, Any]) -> Dict[str, Any]:
    rights = meta.get("rights") if isinstance(meta.get("rights"), dict) else {}
    status = str(rights.get("status") or "unknown").strip().lower()
    return {"status": status if status in RIGHTS else "unknown",
            "death_year": rights.get("death_year"), "note": str(rights.get("note") or "")}


def _source_markdown(meta: Dict[str, Any], text: str, rights: Dict[str, Any]) -> str:
    line = f"Rights: {rights['status']}"
    if rights.get("death_year"):
        line += f" (author died {rights['death_year']})"
    if rights.get("note"):
        line += f" -- {rights['note']}"
    head = [f"# {meta.get('title') or 'Untitled'}", "",
            f"Author: {meta.get('author') or 'unknown'}", line]
    if meta.get("language"):
        head.append(f"Language: {meta['language']}")
    if meta.get("source_url") or meta.get("source"):
        head.append(f"Source: {meta.get('source_url') or meta.get('source')}")
    return "\n".join(head) + "\n\n---\n\n" + text.strip() + "\n"


def _instructions(meta: Dict[str, Any], rights: Dict[str, Any], parts: int, minutes: float, mode: str,
                  title: Optional[str] = None) -> str:
    title, author = title or meta.get("title") or "Untitled", meta.get("author") or "unknown"
    lines = [
        f"Adapt the Story Library story \"{title}\" by {author} (entry {meta.get('id') or ''}).",
        f"The source text is the input asset `source_story` ({SOURCE_REL}); each run holds one part's section "
        "of the story, and its header says which part to write.",
        f"Rights: {rights['status']}.",
    ]
    if mode == "inspired":
        lines.append(
            "It is NOT public domain: do not translate it and do not reuse a single sentence. Write an ORIGINAL "
            "story that keeps only its premise, its mechanic and its fear, with new characters, places and plot, "
            f"and open Part 1 with the line `[inspired-by: {author}, {title}; original story]`.")
    else:
        lines.append("It is public domain: translate and transpose it freely into the creator's spoken Hinglish.")
    lines.append(f"Parts: {parts}, about {minutes:g} minutes each ({parts * minutes:g} minutes in all), "
                 "written one part per run, each under its `# Part N` heading.")
    return "\n".join(lines)


# --- creating the project ------------------------------------------------------------

def _session_format(channel: str) -> str:
    try:
        from app.services import session_format
        return "shorts_first" if session_format.channel_defaults(channel)["shorts_first"] else "long_only"
    except Exception as exc:  # noqa: BLE001 - unreadable settings: the long video only
        logger.warning("Could not read the channel's session format: %s", exc)
        return "long_only"


def adapt(entry_id: str, *, parts: int = 1, minutes_per_part: float = 20, channel: str = DEFAULT_CHANNEL,
          run: bool = True, inspired: bool = False, story_title: Optional[str] = None,
          story_index: Optional[int] = None) -> str:
    """Create the adaptation project (and start its run when `run`); returns its id.
    A collection is split into its stories and only one is adapted: `story_index`
    / `story_title`, else the longest under 12,000 words."""
    from executive.project import project_manager

    meta, text = load_entry(entry_id)
    rights = rights_of(meta)
    if rights["status"] != "public_domain" and not inspired:      # unknown counts as protected
        raise AdaptError(
            f"\"{meta.get('title') or entry_id}\" is {rights['status'].replace('_', ' ')}: it cannot be "
            "translated. Ask for an original story inspired by it instead (inspired=true).")
    mode = "inspired" if (inspired or rights["status"] != "public_domain") else "adaptation"
    parts = max(1, min(MAX_PARTS, int(parts or 1)))
    minutes = max(1.0, min(120.0, float(minutes_per_part or 20)))

    found = split_collection(text)
    index = choose_piece(found, story_title, story_index)
    piece = found[index]
    title = piece["title"] or meta.get("title") or entry_id
    split = len(found) > 1

    name = str(title).strip()
    project = None
    for attempt in range(5):
        try:
            project = project_manager.create_project(
                name=name + (f" {attempt + 1}" if attempt else ""), brand=channel, workflow_name=WORKFLOW)
            break
        except ValueError:
            continue
    if project is None:
        raise RuntimeError("could not create a unique project id")

    source = _source_markdown({**meta, "title": title}, piece["text"], rights)
    for rel in (SOURCE_REL, SOURCE_FULL_REL):
        path = os.path.join(project.get_project_dir(), rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
    project.assets[SOURCE_ASSET] = SOURCE_REL
    project.assets[SOURCE_FULL_ASSET] = SOURCE_FULL_REL
    project.current_step = ADAPT_STEP
    project.metadata["target_duration_minutes"] = parts * minutes
    # Parts are written one per run (run_steps), never through runtime/long_script.py.
    project.metadata["long_script_mode"] = "off"
    project.metadata["adaptation"] = {
        "entry_id": entry_id, "parts": parts, "minutes_per_part": minutes, "rights": rights["status"],
        "mode": mode, "title": meta.get("title"), "author": meta.get("author"),
        "story_title": title, "story_index": index if split else None, "pieces": len(found),
        "story_words": piece["words"], "source_url": meta.get("source_url"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    project.metadata["creator_instructions"] = _instructions(meta, rights, parts, minutes, mode, title)
    project.metadata["session_format"] = _session_format(channel)
    project.save()
    try:
        from app.services.events import bus
        bus.publish("project_created", {"project_id": project.id, "name": project.name, "brand": channel,
                                        "workflow_name": project.workflow_name, "current_step": project.current_step})
    except Exception:  # noqa: BLE001
        pass
    if run:
        start_job(project.id)
    return project.id


# --- the machine-writing report ------------------------------------------------------

def _asset_text(project: Any, key: str) -> str:
    rel = project.assets.get(key)
    return _read(os.path.join(project.get_project_dir(), rel)) if rel else ""


def tells_markdown(report: Dict[str, Any], pass_no: int) -> str:
    lines = ["# Machine-writing tells (ai_tells)", "",
             f"Score: {report['score']}/100 (0 = reads human, 100 = machine). Pass {pass_no} of {HUMAN_MAX_PASSES}.",
             "Rewrite only the lines like the examples below; leave everything else as it is."]
    if pass_no > 1:
        lines.append("This is a second pass: the script input is the previous Human Touch version.")
    if not report["tells"]:
        lines += ["", "No tells found: keep the script as it is."]
    for tell in report["tells"]:
        lines += ["", f"## {tell['kind']} -- {tell['count']}"]
        lines += [f"- \"{example}\"" for example in tell["examples"]]
    return "\n".join(lines) + "\n"


def write_tells(project: Any, source_key: str, pass_no: int = 1) -> Dict[str, Any]:
    """Score `source_key`'s script and save the report as the `ai_tells` asset."""
    from app.services import writing_style
    report = writing_style.ai_tells(_asset_text(project, source_key))
    path = os.path.join(project.get_project_dir(), TELLS_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tells_markdown(report, pass_no))
    project.assets[TELLS_ASSET] = TELLS_REL
    return report


def _score(project: Any, passes: int, report: Dict[str, Any]) -> None:
    project.metadata["human_score"] = report["score"]
    adaptation = dict(project.metadata.get("adaptation") or {})
    adaptation.update(human_passes=passes, human_tells=[t["kind"] for t in report["tells"]])
    project.metadata["adaptation"] = adaptation


# --- running it ----------------------------------------------------------------------

def _after_human_touch(engine: Any, project_id: str, say: Callable[[str], None]) -> None:
    """Score the final script; above the bar, one more Human Touch pass on it."""
    from app.services import writing_style
    from core.models.project import Project

    project = Project.load(project_id)
    report = writing_style.ai_tells(_asset_text(project, "script_final"))
    passes = 1
    _score(project, passes, report)
    project.save()
    say(f"human score {report['score']}/100")
    while report["score"] > HUMAN_RETRY_ABOVE and passes < HUMAN_MAX_PASSES:
        passes += 1
        say(f"step: {HUMAN_STEP} (pass {passes})")
        project = Project.load(project_id)
        final_rel, draft_rel = project.assets.get("script_final"), project.assets.get("script")
        final_path = os.path.join(project.get_project_dir(), final_rel)
        before = _read(final_path)
        resume_step = project.current_step
        write_tells(project, "script_final", passes)
        # The step rewrites its `script` input: point it at the first pass's
        # output for this run, and back at the adaptation after.
        project.assets["script"] = final_rel
        project.current_step = HUMAN_STEP
        project.save()
        error = None
        try:
            engine.execute_next(project_id, allow_all=True)
        except Exception as exc:  # noqa: BLE001 - the first pass stands
            error = str(exc)[:300]
        project = Project.load(project_id)
        project.assets["script"] = draft_rel
        project.current_step = resume_step
        again = writing_style.ai_tells(_read(final_path))
        last = project.steps_history[-1] if project.steps_history else None
        if error or (last is not None and last.step_name == HUMAN_STEP and last.status == "failed"):
            project.steps_history = [h for h in project.steps_history
                                     if not (h is last and h.status == "failed")]
            with open(final_path, "w", encoding="utf-8") as f:
                f.write(before)
            project.metadata.setdefault("adaptation", {})["human_note"] = f"pass {passes} failed: {error or 'step failed'}"
        elif again["score"] > report["score"]:
            with open(final_path, "w", encoding="utf-8") as f:
                f.write(before)
            project.metadata.setdefault("adaptation", {})["human_note"] = (
                f"pass {passes} scored {again['score']}, worse than {report['score']}: kept pass {passes - 1}")
        else:
            report = again
        _score(project, passes, report)
        project.save()
        say(f"human score {report['score']}/100")


def _no_long_script_llm():
    """An LLMService whose config always says `long_script_mode: off`. The
    engine decides on runtime/long_script.py from the LLM service's config
    (reloaded on every call), not from the project, so the Adaptation runs
    get a service that keeps the switch off."""
    from integrations.llm import LLMService

    class _NoLongScript(LLMService):
        def reload_config(self):
            super().reload_config()
            self.config = {**(self.config or {}), "long_script_mode": "off"}

    service = _NoLongScript()
    service.config = {**(service.config or {}), "long_script_mode": "off"}
    return service


def _source_body(markdown: str) -> str:
    return markdown.split("\n\n---\n\n", 1)[1] if "\n\n---\n\n" in markdown else markdown


def adapt_in_parts(project_id: str, progress: Callable[[str], None] = lambda m: None) -> List[str]:
    """The Adaptation step once per part: `source_story` holds only that part's
    section of the story (plus the story so far and the previous part's last
    lines), each part's target is `minutes_per_part`, each output is kept as
    script/part_<k>.md, and the parts are joined into script/script.md -- the
    `script` the Human Touch step then rewrites as a whole."""
    from core.models.project import Project
    from runtime.workflow import WorkflowEngine

    engine = WorkflowEngine(llm_service=_no_long_script_llm())
    project = Project.load(project_id)
    a = dict(project.metadata.get("adaptation") or {})
    minutes = float(a.get("minutes_per_part") or 20)
    total = project.metadata.get("target_duration_minutes")
    base = project.get_project_dir()
    full = _read(os.path.join(base, SOURCE_FULL_REL)) or _read(os.path.join(base, SOURCE_REL))
    chunks = chunk_paragraphs(_source_body(full), int(a.get("parts") or 1))
    outputs: List[str] = []
    try:
        for k, chunk in enumerate(chunks, 1):
            project = Project.load(project_id)
            with open(os.path.join(base, SOURCE_REL), "w", encoding="utf-8") as f:
                f.write(_part_source(a, chunk, k, len(chunks), outputs[-1] if outputs else None))
            project.assets[SOURCE_ASSET] = SOURCE_REL
            project.metadata["target_duration_minutes"] = minutes
            project.current_step = ADAPT_STEP
            project.save()
            progress(f"step: {ADAPT_STEP} (part {k} of {len(chunks)})")
            project = engine.execute_next(project_id, allow_all=True)
            last = project.steps_history[-1] if project.steps_history else None
            if last and last.status == "failed":
                raise RuntimeError(f"step '{last.step_name}' failed on part {k}")
            text = _asset_text(project, "script")
            with open(os.path.join(base, "script", f"part_{k}.md"), "w", encoding="utf-8") as f:
                f.write(text)
            outputs.append(text)
    finally:
        project = Project.load(project_id)
        project.metadata["target_duration_minutes"] = total
        if full:
            with open(os.path.join(base, SOURCE_REL), "w", encoding="utf-8") as f:
                f.write(full)
        project.save()
    with open(os.path.join(base, SCRIPT_REL), "w", encoding="utf-8") as f:
        f.write(join_parts(outputs))
    project = Project.load(project_id)
    project.assets["script"] = SCRIPT_REL
    project.metadata.setdefault("adaptation", {})["parts_written"] = len(outputs)
    project.save()
    return outputs


def run_steps(project_id: str, progress: Callable[[str], None] = lambda m: None) -> Dict[str, Any]:
    """Run the adaptation's steps with approvals bypassed, up to the Visual Plan."""
    from core.models.project import Project
    from runtime.workflow import WorkflowEngine

    project = Project.load(project_id)
    if project.current_step == ADAPT_STEP:
        adapt_in_parts(project_id, progress)
        project = Project.load(project_id)
    engine = WorkflowEngine()
    for _ in range(MAX_STEPS):
        if project.current_step in DONE_STEPS or project.status == "completed":
            break
        step = project.current_step
        if step == HUMAN_STEP:
            write_tells(project, "script", 1)
            project.save()
        progress(f"step: {step}")
        project = engine.execute_next(project_id, allow_all=True)
        last = project.steps_history[-1] if project.steps_history else None
        if last and last.status == "failed":
            raise RuntimeError(f"step '{last.step_name}' failed")
        if step == HUMAN_STEP and project.current_step != HUMAN_STEP:
            _after_human_touch(engine, project_id, progress)
            project = Project.load(project_id)
    # Hand it back to the creator: later steps pause for approval again.
    project = Project.load(project_id)
    project.metadata["allow_all"] = False
    project.metadata.setdefault("adaptation", {})["built_at"] = datetime.now().isoformat(timespec="seconds")
    project.save()
    return {"project_id": project.id, "current_step": project.current_step,
            "human_score": project.metadata.get("human_score")}


# --- jobs (the run goes in the background; the UI polls) ------------------------------

_jobs: Dict[str, Dict[str, Any]] = {}


def start_job(project_id: str) -> Dict[str, Any]:
    from integrations import idle_offload
    job_id = uuid.uuid4().hex[:12]
    job = {"job_id": job_id, "kind": "adapt", "project_id": project_id, "state": "running",
           "message": "Starting", "result": None, "error": None,
           "started_at": datetime.now().isoformat(timespec="seconds")}
    _jobs[job_id] = job

    def progress(msg: str) -> None:
        job["message"] = msg

    def run() -> None:
        try:
            with idle_offload.busy():
                job["result"] = run_steps(project_id, progress)
            job["state"] = "done"
            job["message"] = "Done"
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            logger.exception("story adaptation %s failed", project_id)
            job.update(state="failed", error=str(exc)[:300])
        finally:
            idle_offload.offload_now("story adaptation finished")

    threading.Thread(target=run, name=f"story-adapt-{job_id}", daemon=True).start()
    return job


def job(job_id: str) -> Optional[Dict[str, Any]]:
    return _jobs.get(job_id)


def _job_for(project_id: str) -> Optional[Dict[str, Any]]:
    found = [j for j in _jobs.values() if j.get("project_id") == project_id]
    return found[-1] if found else None


def status(project_id: str) -> Dict[str, Any]:
    """The adaptation's progress for the UI."""
    from core.models.project import Project
    project = Project.load(project_id)
    adaptation = project.metadata.get("adaptation") or {}
    running = _job_for(project_id)
    last = project.steps_history[-1] if project.steps_history else None
    if running and running["state"] == "running":
        state = "running"
    elif (running and running["state"] == "failed") or (last and last.status == "failed"):
        state = "failed"
    elif project.current_step in (STOP_STEP, "Completed") or project.status == "completed":
        state = "ready"
    else:
        state = "created"
    return {
        "project_id": project.id, "state": state, "human_score": project.metadata.get("human_score"),
        "parts": adaptation.get("parts"), "rights": adaptation.get("rights"), "mode": adaptation.get("mode"),
        "current_step": project.current_step, "job_id": running["job_id"] if running else None,
        "steps": [{"name": h.step_name, "agent": h.agent_name, "status": h.status,
                   "started_at": h.started_at, "completed_at": h.completed_at}
                  for h in project.steps_history],
    }
