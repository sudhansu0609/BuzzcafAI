"""Long scripts (30-90+ minutes) that a small local model can still write well.

A 12B local model asked for 12,000 words in one reply stops early, loses the
thread or starts repeating itself. So a long script step runs as many short,
fully-grounded calls instead of one huge one:

1. **Plan** -- one call returns a story bible (characters, names, setting, the
   rules, key facts, recurring motifs) and a section outline whose word
   budgets add up to the target.
2. **Write** -- one call per section (~700 words). Every call carries the
   brief, the bible, the whole outline, one-line summaries of what is already
   written and the last ~180 words verbatim, so the voice and continuity hold
   and the joins are seamless. A short section gets a "continue" call; a
   section that repeats earlier material is rewritten once.
3. **Checkpoint** -- the plan and each finished section are saved under
   `script/sections/<asset>/`, so a failed run resumes where it stopped.

Rewrite passes (edit / narration) on a long script go chunk by chunk too, and
a chunk the model truncates keeps its original text -- nothing is ever lost.

The persona's system prompt is used without its memory log: that log is
several thousand tokens of unrelated past tasks, and a small model's context
is better spent on the script itself.

Budgets count the words that are SAID (`words`): cue lines and speaker labels
are not runtime. With a `StyleGate` (the creator's own writing style, "my
style" mode) every section and every rewritten part is scored against his
style as it is written and rewritten once when it is off, and when he writes
continuous narration the script is laid out that way instead of as a
screenplay.
"""

import json
import logging
import math
import os
import re
import shutil
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("buzzcaf_ai.engine.long_script")

DEFAULTS = {
    "long_script_mode": "auto",            # auto | always | off
    "long_script_threshold_minutes": 12,   # auto: sectioned above this target
    "long_script_section_words": 700,      # per-call budget a small model writes well
    "long_script_rewrite_chunk_words": 900,
    "long_script_plan_review": True,       # one extra call: the plan is judged and strengthened as a story
}
MAX_CONTINUATIONS = 2
RETRIES_ON_FAILURE = 2
TAIL_WORDS = 180
SUMMARY_RE = re.compile(r"^\s*\**SUMMARY\**\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def _cfg(config: Dict[str, Any], key: str):
    value = (config or {}).get(key)
    return DEFAULTS[key] if value in (None, "") else value


def words(text: str) -> int:
    """The words that are said: a 3,400-word script that is half [VISUAL] cues
    is a 12-minute video, not a 24-minute one."""
    from app.services.writing_style import narration_words
    return narration_words(text)


class StyleGate:
    """The creator's own writing style, applied piece by piece.

    `check(text)` scores a piece (None when there is nothing to compare with),
    `revise_task(text, result)` is the prompt that rewrites it toward his
    style, `below` the score under which that happens, and `narration` says he
    writes continuous narration, so no screenplay layout is asked for.
    `reminder` is his sentence rhythm in a few lines, repeated next to every
    section's instruction."""

    def __init__(self, check: Callable[[str], Optional[Dict[str, Any]]],
                 revise_task: Callable[[str, Dict[str, Any]], str], below: int, narration: bool,
                 reminder: str = ""):
        self.check = check
        self.revise_task = revise_task
        self.below = below
        self.narration = narration
        self.reminder = reminder


def match_style(call: "Caller", gate: Optional[StyleGate], text: str, log: Callable[[str], None], label: str) -> str:
    """One rewrite toward the creator's style when a piece scores below the
    gate; the closer version is kept, and never one that lost spoken words."""
    if gate is None:
        return text
    try:
        result = gate.check(text)
        if result is None or result["score"] >= gate.below:
            return text
        from runtime.workflow import _unwrap_script  # local import: avoids a cycle
        revised = SUMMARY_RE.sub("", _unwrap_script(call(gate.revise_task(text, result)))).strip()
        again = gate.check(revised) if revised else None
        if again is not None and again["score"] > result["score"] and words(revised) >= 0.8 * words(text):
            log(f"{label}: creator style {result['score']} -> {again['score']}/100 after a rewrite toward his style.")
            return revised
        log(f"{label}: creator style {result['score']}/100; the rewrite was not closer (or came back short), kept.")
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - the style pass never fails a script
        logger.warning(f"Long script: style pass failed for {label}: {exc}")
    return text


def once_opened(text: str, opening: bool, log: Callable[[str], None], label: str) -> str:
    """The host's greeting and opening lines in the opening piece only, once.
    A model shown the opening for every section (or every rewrite part) tends
    to re-open the video there; whatever the prompts did not prevent is cut."""
    try:
        from app.services.writing_style import strip_repeated_intro
        cleaned, removed = strip_repeated_intro(text, keep_first=opening)
    except Exception as exc:  # noqa: BLE001 - never fails a script
        logger.warning(f"{label}: could not check for a repeated greeting: {exc}")
        return text
    if removed:
        log(f"{label}: removed {removed} repeated greeting(s) and the opening lines around them.")
    return cleaned


def tail(text: str, n: int = TAIL_WORDS) -> str:
    w = (text or "").split()
    return " ".join(w[-n:])


def should_section(config: Dict[str, Any], target_words: int) -> bool:
    mode = str(_cfg(config, "long_script_mode")).lower()
    if mode == "off" or target_words <= 0:
        return False
    if mode == "always":
        return True
    threshold = float(_cfg(config, "long_script_threshold_minutes")) * 140
    return target_words > threshold


def should_chunk_rewrite(config: Dict[str, Any], source_words: int) -> bool:
    mode = str(_cfg(config, "long_script_mode")).lower()
    if mode == "off":
        return False
    return mode == "always" or source_words > int(_cfg(config, "long_script_rewrite_chunk_words")) * 1.6


def _parse_json(text: str) -> Optional[Any]:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rsplit("```", 1)[0]
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(s[start:end + 1], strict=False)
    except ValueError:
        return None


def _shingles(text: str, n: int = 8) -> set:
    w = re.findall(r"\w+", (text or "").lower())
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def repetition_ratio(new: str, earlier: List[str]) -> float:
    """Share of the new section's 8-word runs that already appear earlier."""
    fresh = _shingles(new)
    if not fresh or not earlier:
        return 0.0
    seen = set()
    for e in earlier:
        seen |= _shingles(e)
    return len(fresh & seen) / len(fresh)


class Caller:
    """One model call as the persona, without its memory log."""

    def __init__(self, agent):
        self.agent = agent
        try:
            agent.refresh_prompt()
        except Exception:
            pass
        self.system = getattr(agent, "system_prompt", "") or ""
        self.llm = agent.llm_service

    def __call__(self, user_prompt: str, require_json: bool = False, temperature: Optional[float] = None) -> str:
        temp = getattr(self.agent, "temperature", None) if temperature is None else temperature
        # A local engine hiccup ("failed to decode") makes LLMService return
        # canned demo text in development; that must never land in a script.
        for attempt in range(RETRIES_ON_FAILURE + 1):
            out = self.llm.generate_text(system_prompt=self.system, user_prompt=user_prompt,
                                         require_json=require_json, tier=getattr(self.agent, "model_tier", None),
                                         temperature=temp)
            if not getattr(self.llm, "last_response_simulated", False):
                return str(out or "")
            logger.warning(f"Long script: the model call failed (simulated reply), retry {attempt + 1}.")
            time.sleep(5 * (attempt + 1))
        raise RuntimeError("The model kept failing mid-script; the finished sections are saved -- re-run the step to resume.")


_PREAMBLE_RE = re.compile(
    r"^\s*(hello|hi|hey|namaste|sure|certainly|of course|okay|ok|absolutely|great|here is|here's|here are|"
    r"i am your|i'm your|as an ai|below is|what .* shall we|how can i help|let me)\b", re.IGNORECASE)


def clean_section(text: str, heading: str) -> str:
    """Drop chat-style preamble before the script starts and make sure the section heading is there."""
    lines = (text or "").strip().splitlines()
    head_at = next((k for k, l in enumerate(lines) if l.lstrip().startswith("## [SECTION")), None)
    if head_at is not None:
        lines = lines[head_at:]
    else:
        # Skip leading chatty paragraphs (and the bullet list that follows them)
        # -- but "Hello doston, ..." is the host greeting the viewer, not the model.
        k = 0
        while k < len(lines) and (not lines[k].strip() or (_PREAMBLE_RE.match(lines[k]) and "dosto" not in lines[k].lower())
                                  or (k > 0 and lines[k].lstrip().startswith(("- ", "* ")) and _PREAMBLE_RE.match(lines[0]))):
            k += 1
        lines = [heading, ""] + lines[k:]
    # Drop a trailing "anything else?" style line.
    while lines and _PREAMBLE_RE.match(lines[-1]) and "?" in lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


# --- writing a long script ----------------------------------------------------------

# How a section is laid out: the studio's cue format, or -- when the creator's
# own written samples are continuous narration -- his.
FORMAT_CUES = ("in the same script format as the rest (headings, V.O. lines, [VISUAL]/[SOUND] cues, "
               "(pause)/(slow) delivery cues)")
FORMAT_NARRATION = ("as continuous narration in the creator's own format (\"Format\" in his writing style above): "
                    "full paragraphs told to the listener, what people say told inside the narration. No "
                    "[VISUAL]/[SOUND] cues, no speaker labels such as NAME (V.O.), no (pause)/(slow) marks, no "
                    "English descriptions -- what is seen and heard is narrated in Hinglish")
VOICE_CHANNEL = "in the channel's voice (the guide above)"
VOICE_CREATOR = "in the creator's own voice (his writing style above), point of view included"
PLAN_STYLE = """- The script is told in the creator's own writing style (above). Plan it for his way of telling a
  story: his point of view (when he tells stories as "main", the narrator IS the person it happened to --
  say who that is in "narration"), his fixed greeting and his opening in section 1, his way of ending in
  the last section.
- Section titles are short Hinglish chapter titles in Roman script, like his own.
"""

PLAN_PROMPT = """{context}

### Your job right now: PLAN the script (do not write it yet)
The full script will be about {minutes:g} minutes -- {target:,} spoken words -- and will be written
section by section from your plan, so the plan must carry everything needed to keep it consistent.

Return strict JSON only:
{{"bible": {{"characters": [{{"name": "...", "who": "...", "voice": "..."}}],
            "narration": "who tells the story: point of view (main / woh) and tense",
            "setting": "...", "rules": ["every rule, numbered, if the story has rules"],
            "key_facts": ["facts / folklore / real details from the research the script relies on"],
            "layers": {{"surface": "what seems to be happening", "beneath": "what is really going on: the hidden history",
                       "truth": "the final understanding that changes the meaning of everything before it"}},
            "plants": ["a concrete detail planted early -> how it pays off later (3-6 of these)"],
            "escalation": ["incident 1: odd", "incident 2: wrong", "incident 3: threatening", "incident 4: undeniable"],
            "twist": "the ending's reveal, and which plants make it earned rather than random",
            "motifs": ["recurring images, sounds, lines -- and how their meaning changes"], "tone": "...",
            "ending": "the last scene and the final line"}},
 "sections": [{{"title": "...", "purpose": "what this section must achieve",
               "beats": ["3-6 concrete beats, in order"], "words": 0}}]}}

Rules for the plan:
- Exactly {n} sections, in order, following the structure the brief and the channel guide ask for.
- The "words" values must add up to about {target:,}; give heavier sections more.
- Beats are concrete events, lines of inquiry or reveals -- never "continue the story" or "build tension".
- No two sections may cover the same beat.
- Plan a full, detailed telling: every section needs enough concrete beats (events, conversations,
  discoveries) to fill its words with story.
- A LAYERED story, not a chain of scares: the surface events, the hidden history underneath them, and a
  truth at the end that re-reads the earlier scenes. Every section carries at least one plant or payoff
  from "plants". Each incident in "escalation" is worse and more specific than the one before. The twist
  must be earned by the plants and leave one thing unresolved.
- Specific, not generic: real texture from the research package (real places, duty routines, objects,
  local words, folklore rules with their exact conditions), named characters with a life outside the story,
  and a reason they cannot simply leave. Never the hundredth "a ghost in the jungle" video.
- The story is this project's own: never retell or borrow the story, characters, place or lines of any
  example quoted in the creator's writing style; those show his manner only.
{style}"""

PLAN_REVIEW_PROMPT = """{context}

### Your job right now: JUDGE and STRENGTHEN this plan (do not write the script yet)
A writer drafted this plan for a {minutes:g}-minute script ({target:,} spoken words):

{plan}

Read it as a hard-to-please story editor who has seen every jungle-ghost, haunted-haveli and
highway-spirit video. Ask:
- Is it layered -- surface events, a hidden history underneath, and a truth at the end that changes the
  meaning of what came before? Or is it just one scare after another?
- Is the twist earned by concrete plants placed earlier, and does it leave one thing unresolved?
- Does every incident escalate, each more specific and worse than the last?
- Is it specific (real texture from the research, named people with a life, a reason they cannot leave),
  or generic? Does any part copy the creator's quoted examples instead of being this story's own?
- Does each section have enough concrete beats to fill its words with story, not padding?

Return the IMPROVED plan as strict JSON with exactly the same shape and keys ("bible" and "sections"),
the same number of sections and about the same total words: rewrite the weak parts (sharper plants
and payoffs, a stronger twist, more specific incidents, more concrete beats), keep what already works.
If it is already strong, return it unchanged. JSON only, nothing else.
"""

SECTION_PROMPT = """{context}

### The plan for the whole script
Story bible (keep every name, rule and fact exactly as written here):
{bible}

Outline:
{outline}

### Already written
{done}

### Your job right now
Write SECTION {i} of {n}: "{title}" -- about {budget} spoken words.
Purpose: {purpose}
Beats to cover, in order:
{beats}

{position}
- Language: Hinglish in Roman script for every spoken line, {voice}.
- Write only this section, {format}.
{reminder}- Tell it in full: every beat is a complete scene -- where we are, who is there, what is said, what is seen,
  heard and felt, what the character thinks and does next. Never sum a beat up in a line or two. Reach the
  {budget} spoken words with story and detail, never with filler, repetition or stage directions.
- Where the bible's plants, escalation or motifs belong in this section, place them here, concretely, as
  things seen, said or found -- never explained by the narrator.
- Start with the heading: ## [SECTION {i}: {title}]
- Do not recap earlier sections, do not re-introduce the host or the story, do not skip ahead to later beats.
- Plain Markdown only -- no JSON, no code fences, no notes to me.
- After the section, on its own last line, write: SUMMARY: <one or two sentences of what happened in this section>
"""

NO_OPENING = ("- The video was already opened in section 1: this section begins INSIDE the story. No greeting "
              "(no \"Hello doston\" or any other), no host or channel name, no \"aaj ki kahani ...\" line, no "
              "subscribe request, no \"toh chaliye ...\" transition, no re-introduction of the story.")

CONTINUE_PROMPT = """{context}

Story bible:
{bible}

You are writing SECTION {i} of {n}: "{title}". Purpose: {purpose}
Beats: {beats}

It is unfinished -- about {missing} more spoken words are needed. This is the section so far:
<<<
{so_far}
>>>

Everything above is already told: never tell any of it again, in the same or in other words (no recap,
no second introduction of the place, the people or the objects, and never a greeting or the video's
opening lines). Continue from EXACTLY where it stops (no heading): move the story FORWARD with what
happens next -- the beats not yet covered, in full detail, as new scenes -- and finish the section.
Write it {format}. {reminder}Plain Markdown only. Last line: SUMMARY: <one or two sentences for the whole section>
"""


class LongScriptWriter:
    def __init__(self, agent, config: Dict[str, Any], work_dir: str, log: Callable[[str], None],
                 style: Optional[StyleGate] = None):
        self.call = Caller(agent)
        self.config = config or {}
        self.dir = work_dir
        self.log = log
        self.style = style
        self.narration = bool(style and style.narration)
        self.format = FORMAT_NARRATION if self.narration else FORMAT_CUES
        self.reminder = (style.reminder if style else "") or ""

    # checkpoints
    def _path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def reset(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _save(self, name: str, text: str) -> None:
        os.makedirs(self.dir, exist_ok=True)
        with open(self._path(name), "w", encoding="utf-8") as f:
            f.write(text)

    def _load(self, name: str) -> Optional[str]:
        try:
            with open(self._path(name), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    # phases
    def plan(self, context: str, minutes: float, target: int) -> Dict[str, Any]:
        cached = _parse_json(self._load("plan.json") or "")
        if cached and cached.get("target") == target and cached.get("sections"):
            self.log(f"Long script: resuming with the saved plan ({len(cached['sections'])} sections).")
            return cached
        per = int(_cfg(self.config, "long_script_section_words"))
        n = max(2, math.ceil(target / per))
        plan = None
        for attempt in range(3):
            raw = self.call(PLAN_PROMPT.format(context=context, minutes=minutes, target=target, n=n,
                                               style=PLAN_STYLE if self.narration else ""),
                            require_json=True, temperature=0.5)
            plan = _parse_json(raw)
            if plan and isinstance(plan.get("sections"), list) and len(plan["sections"]) >= max(2, n // 2):
                break
            self.log(f"Long script: plan attempt {attempt + 1} was unusable, retrying.")
            plan = None
        if not plan:
            raise ValueError("The model could not produce a usable section plan for the long script.")
        sections = [s for s in plan["sections"] if isinstance(s, dict)]
        # Rescale the budgets so they add up to the target, each within sane bounds.
        raw_budgets = [max(1, int(s.get("words") or 0) or per) for s in sections]
        scale = target / sum(raw_budgets)
        for s, b in zip(sections, raw_budgets):
            s["words"] = int(min(per * 1.6, max(per * 0.4, b * scale)))
        plan = {"target": target, "bible": plan.get("bible") or {}, "sections": sections}
        plan = self._review_plan(context, plan, minutes, target)
        self._save("plan.json", json.dumps(plan, ensure_ascii=False, indent=2))
        self.log(f"Long script: planned {len(plan['sections'])} sections for ~{target:,} words.")
        return plan

    def _review_plan(self, context: str, plan: Dict[str, Any], minutes: float, target: int) -> Dict[str, Any]:
        """One call as a story editor: the plan judged for layers, plants and
        payoffs, escalation, an earned twist and specificity, and returned
        strengthened in the same shape. Anything unusable keeps the original."""
        if not _cfg(self.config, "long_script_plan_review"):
            return plan
        try:
            shown = {"bible": plan["bible"], "sections": plan["sections"]}
            raw = self.call(PLAN_REVIEW_PROMPT.format(context=context, minutes=minutes, target=target,
                                                      plan=json.dumps(shown, ensure_ascii=False, indent=1)),
                            require_json=True, temperature=0.5)
            better = _parse_json(raw)
            sections = [s for s in (better or {}).get("sections") or [] if isinstance(s, dict) and s.get("title")]
            if not better or not isinstance(better.get("bible"), dict) or len(sections) != len(plan["sections"]):
                self.log("Long script: the plan review came back unusable; the first plan is kept.")
                return plan
            for s, old in zip(sections, plan["sections"]):  # the budgets stay as planned
                s["words"] = old["words"]
                s.setdefault("beats", old.get("beats") or [])
            bible = dict(plan["bible"])
            bible.update(better["bible"])
            self.log("Long script: the plan was reviewed and strengthened as a layered story.")
            return {"target": target, "bible": bible, "sections": sections}
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001 - a failed review never fails the script
            logger.warning(f"Long script: plan review failed: {exc}")
            return plan

    def _section(self, context: str, plan: Dict[str, Any], i: int, written: List[Dict[str, str]]) -> Dict[str, str]:
        sections = plan["sections"]
        s = sections[i]
        n = len(sections)
        bible = json.dumps(plan["bible"], ensure_ascii=False, indent=1)
        outline = "\n".join(
            f"{k + 1}. {x.get('title', '')} -- {x.get('purpose', '')}" + ("   <-- YOU ARE HERE" if k == i else "")
            for k, x in enumerate(sections)
        )
        if written:
            done = "\n".join(f"- Section {k + 1}: {w['summary']}" for k, w in enumerate(written))
            done += f"\n\nThe script so far ends with:\n<<<\n{tail(written[-1]['text'])}\n>>>"
        else:
            done = "Nothing yet -- this is the opening."
        if i == 0 and self.narration:
            position = ("- This is the OPENING of the video: open exactly as the creator opens (his fixed greeting "
                        "word for word, then his intro lines, from his writing style above), then begin the story. "
                        "The greeting is said ONCE, here, and never again anywhere in the script.")
        elif i == 0:
            position = "- This is the OPENING of the video: start with the hook."
        elif i == n - 1 and self.narration:
            position = ("- This is the FINAL section: land the ending from the bible and close the video the way "
                        "the creator ends his (his writing style above).\n" + NO_OPENING)
        elif i == n - 1:
            position = "- This is the FINAL section: land the ending from the bible and close the video.\n" + NO_OPENING
        else:
            position = ("- Continue seamlessly from where the script ends above. This is the middle -- do not wrap up "
                        "the video.\n" + NO_OPENING)
        beats = "\n".join(f"- {b}" for b in (s.get("beats") or [])) or "- (as the purpose says)"
        budget = int(s.get("words") or 700)
        prompt = SECTION_PROMPT.format(context=context, bible=bible, outline=outline, done=done, i=i + 1, n=n,
                                       title=s.get("title", ""), budget=budget, purpose=s.get("purpose", ""),
                                       beats=beats, position=position, format=self.format,
                                       reminder=f"- {self.reminder}\n" if self.reminder else "",
                                       voice=VOICE_CREATOR if self.narration else VOICE_CHANNEL)

        earlier = [w["text"] for w in written]
        best = None
        for attempt in range(2):
            text, summary = self._split_summary(self.call(prompt))
            for _ in range(MAX_CONTINUATIONS):
                if words(text) >= budget * 0.85:
                    break
                more, summary2 = self._split_summary(self.call(CONTINUE_PROMPT.format(
                    context=context, bible=bible, i=i + 1, n=n, title=s.get("title", ""),
                    purpose=s.get("purpose", ""), beats="; ".join(s.get("beats") or []),
                    missing=budget - words(text), so_far=text.strip(), format=self.format,
                    reminder=f"{self.reminder} " if self.reminder else "")))
                if words(more) < 20:
                    break
                text = text.rstrip() + "\n\n" + more.strip()
                summary = summary2 or summary
            rep = repetition_ratio(text, earlier)
            if best is None or rep < best[2]:
                best = (text, summary, rep)
            if rep <= 0.2:
                break
            self.log(f"Long script: section {i + 1} repeated earlier material ({rep:.0%}); rewriting it.")
            prompt += "\n- IMPORTANT: your last attempt repeated earlier sections. Every line must be new.\n"
        text, summary, _ = best
        text = match_style(self.call, self.style, text, self.log, f"Long script: section {i + 1}")
        text = clean_section(text, f"## [SECTION {i + 1}: {s.get('title', '')}]")
        text = once_opened(text, opening=(i == 0), log=self.log, label=f"Long script: section {i + 1}")
        if self.narration:
            # The chapter title once, as the heading: not again as a line of its own.
            title = re.sub(r"\W+", " ", str(s.get("title", ""))).strip().lower()
            kept = [l for k, l in enumerate(text.splitlines())
                    if k == 0 or not title or re.sub(r"\W+", " ", l).strip().lower() != title]
            text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
        if not summary:
            summary = " ".join(re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))[-2:])[:300]
        return {"text": text.strip(), "summary": summary.strip()}

    @staticmethod
    def _split_summary(raw: str):
        from runtime.workflow import _unwrap_script  # local import: avoids a cycle
        text = _unwrap_script(raw)
        found = SUMMARY_RE.findall(text)
        summary = found[-1].strip() if found else ""
        text = SUMMARY_RE.sub("", text).strip()
        return text, summary

    def write(self, context: str, minutes: float, target: int) -> str:
        plan = self.plan(context, minutes, target)
        written: List[Dict[str, str]] = []
        n = len(plan["sections"])
        for i in range(n):
            name = f"section_{i + 1:02d}.json"
            cached = _parse_json(self._load(name) or "")
            if cached and cached.get("text"):
                written.append(cached)
                continue
            # Master pause (docs/STUDIO_DIRECTOR_PLAN.md Part 1): between
            # sections, before the next one starts -- each finished section
            # is already checkpointed to disk, so holding here never loses
            # one, and a restart (or a resume) picks up at the same `name`.
            from app.services import master_control
            master_control.wait_if_paused(f"long_script: section {i + 1}/{n}", self.log)
            part = self._section(context, plan, i, written)
            self._save(name, json.dumps(part, ensure_ascii=False))
            written.append(part)
            total = sum(words(w["text"]) for w in written)
            self.log(f"Long script: section {i + 1}/{n} done ({words(part['text'])} words, {total:,} so far).")
        text = "\n\n".join(w["text"] for w in written).strip() + "\n"
        if self.narration:
            # His chapters carry a plain title, not a "[SECTION 3: ...]" slug.
            text = _SECTION_HEADING_RE.sub(r"## \1", text)
        return text


_SECTION_HEADING_RE = re.compile(r"(?m)^## \[SECTION \d+:\s*(.+?)\]\s*$")


# --- rewriting a long script in chunks ------------------------------------------------

REWRITE_PROMPT = """{context}

### Your job right now
The script is long, so it is being processed in parts. This is PART {i} of {n}.
Apply the task above to THIS PART ONLY and return the COMPLETE rewritten part: every heading and every
spoken line{cues} -- same order, nothing summarised, nothing skipped, nothing
added from other parts. Plain Markdown only, no JSON, no code fences, no comments to me.
{opening}

{neighbours}
### PART {i} of {n} (rewrite this)
<<<
{chunk}
>>>
"""

_HEADING_RE = re.compile(r"(?m)^(?=#{1,3} |\*\*\[?SCENE|\[SCENE|## \[)")


def split_script(text: str, target_words: int) -> List[str]:
    """Chunks of about `target_words`, cut at headings when possible, else at paragraphs."""
    blocks = [b for b in _HEADING_RE.split(text) if b.strip()]
    pieces: List[str] = []
    for b in blocks:  # oversized blocks fall back to paragraph cuts
        if words(b) <= target_words * 1.5:
            pieces.append(b)
            continue
        cur: List[str] = []
        for para in re.split(r"\n\s*\n", b):
            cur.append(para)
            if words("\n\n".join(cur)) >= target_words:
                pieces.append("\n\n".join(cur))
                cur = []
        if cur:
            pieces.append("\n\n".join(cur))
    chunks: List[str] = []
    cur_text = ""
    for p in pieces:
        if cur_text and words(cur_text) + words(p) > target_words * 1.3:
            chunks.append(cur_text)
            cur_text = p
        else:
            cur_text = (cur_text + "\n\n" + p) if cur_text else p
    if cur_text.strip():
        chunks.append(cur_text)
    return [c.strip() for c in chunks if c.strip()]


REWRITE_OPENING = ("This is the OPENING part: it keeps the host's greeting and opening lines exactly as they are, "
                   "once, and nothing greets the viewer a second time.")
REWRITE_MIDDLE = ("This part is from the MIDDLE or the END of the video. It has no greeting and must not get one: "
                  "no \"Hello doston\" or any other greeting, no host or channel name, no \"aaj ki kahani ...\" "
                  "line, no subscribe request, no re-introduction of the story.")

REWRITE_CUES = ", every [VISUAL]/[SOUND] cue"
REWRITE_NARRATION = (". The script is continuous narration in the creator's own format and stays so: add no "
                     "[VISUAL]/[SOUND] cues, speaker labels or (pause) marks, and where this part has any, tell "
                     "what matters in words inside the narration and drop the rest")


def rewrite_in_chunks(agent, config: Dict[str, Any], context: str, script: str,
                      log: Callable[[str], None], style: Optional[StyleGate] = None) -> str:
    from runtime.workflow import _unwrap_script
    call = Caller(agent)
    chunks = split_script(script, int(_cfg(config, "long_script_rewrite_chunk_words")))
    out: List[str] = []
    kept = 0
    for i, chunk in enumerate(chunks):
        neighbours = ""
        if i > 0:
            neighbours += f"(For flow only -- the previous part ends with: \"{tail(chunks[i - 1], 60)}\")\n"
        if i < len(chunks) - 1:
            neighbours += f"(For flow only -- the next part begins with: \"{' '.join(chunks[i + 1].split()[:40])}\")\n"
        prompt = REWRITE_PROMPT.format(context=context, i=i + 1, n=len(chunks), neighbours=neighbours, chunk=chunk,
                                       cues=REWRITE_NARRATION if style and style.narration else REWRITE_CUES,
                                       opening=REWRITE_OPENING if i == 0 else REWRITE_MIDDLE)
        result = None
        for _ in range(2):
            candidate = _unwrap_script(call(prompt)).strip()
            if words(candidate) >= words(chunk) * 0.6:
                result = candidate
                break
        if result is None:
            kept += 1
            result = chunk
            log(f"Rewrite: part {i + 1}/{len(chunks)} came back truncated twice; kept the original text.")
        result = match_style(call, style, result, log, f"Rewrite: part {i + 1}/{len(chunks)}")
        result = once_opened(result, opening=(i == 0), log=log, label=f"Rewrite: part {i + 1}/{len(chunks)}")
        out.append(result)
        log(f"Rewrite: part {i + 1}/{len(chunks)} done.")
    if kept == len(chunks):
        raise ValueError("The model truncated every part of the rewrite; nothing was changed.")
    return "\n\n".join(out).strip() + "\n"
