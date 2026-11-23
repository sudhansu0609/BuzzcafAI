"""The long-form half of the nightly run (nightly_run.py): new videos per
channel, taken as far as a machine can take it without the creator.

For each channel in `longform_nightly_channels` (Raat3Baje, Beyond3Baje,
Life3Baje by default) the channel strategist plans the video, following the
creator's own instructions for that channel (`longform_nightly_instructions`,
edited on the Projects -> Long-form panel). It runs as a tool loop
(app/services/strategist_runner.py): it can call every Studio agent, search
the web / books / news / archives, read the Topic Vault and the Idea Dump,
analyse YouTube videos and channels, and run the Studio's safe actions, and
then writes a plan -- which topic (from the vault, the Idea Dump, or a new
one), the angle, and a creative brief for the writer.

A project is created on the channel's workflow with that brief and the
creator's instructions in its metadata (the workflow engine puts both in
every step's prompt), and the pre-production steps run with approvals
bypassed -- research, then script -- stopping at "Visual Plan" so the
morning starts with a researched, scripted project to review and record.

If the strategist cannot plan (no model, no plan in time), the run falls back
to the best vault topic, then the oldest unused Idea Dump idea, still with the
creator's instructions attached.

Live status (each channel's stage plus every tool and agent call) is written
to knowledge/nightly/longform_status.json while a run is going, so the panel
can show it for a Run-now and for the 03:00 run alike. The record (and a
30-run history) lives in knowledge/nightly/longform.json; `last_run` there
stops a second nightly run on the same day.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.longform_nightly")

DEFAULT_CHANNELS = ["Raat3Baje", "Beyond3Baje", "Life3Baje"]

#: Channel -> workflow, the same table the frontend uses (lib/channels.ts).
#: TheTallStoryteller is wired in here (so Auto Story / the Story Desk's
#: long_story format can plan and build it) but is not in DEFAULT_CHANNELS
#: below, so the nightly run leaves it alone until the creator adds it to
#: `longform_nightly_channels`.
WORKFLOWS = {
    "Raat3Baje": "after_dark_narration",
    "Beyond3Baje": "beyond3baje_documentary",
    "Life3Baje": "life3baje_video",
    "TheTallStoryteller": "thetallstoryteller_story",
}

#: The run stops once the project reaches this step: everything before it is
#: research and script, everything from it on wants the creator's review.
DEFAULT_MINUTES = 8.0

STOP_STEP = "Visual Plan"   # kept for callers that still name it; the run no longer stops here
#: The run goes on through every planning step (Visual Plan, Sound Design, Scene
#: Breakdown, Shot List, Clip/Image Planning, SEO & Thumbnail ...) and stops at the
#: first step that needs the creator himself: his recording (the fresh on-camera
#: intro), the edit, review or publishing. Creator, 2026-10-24: "let's not wait from
#: now on on the visual plan".
HUMAN_STEPS = ("Voice Recording", "Editing", "Review", "Publishing", "Analytics", "Completed")
MAX_STEPS = 14


def _needs_creator(step: Any) -> bool:
    return str(step or "") in HUMAN_STEPS


def _record_path() -> str:
    return os.path.join(str(KNOWLEDGE_DIR), "nightly", "longform.json")


def _read_record() -> Dict[str, Any]:
    try:
        with open(_record_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _minutes(raw: Any) -> Dict[str, float]:
    """Target length per channel. An older single number applies to all."""
    if isinstance(raw, (int, float)):
        return {ch: float(raw) for ch in WORKFLOWS}
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for ch in WORKFLOWS:
        try:
            out[ch] = float(raw.get(ch, DEFAULT_MINUTES))
        except (TypeError, ValueError):
            out[ch] = DEFAULT_MINUTES
    return out


#: Channels whose long-form episodes take turns between formats: each built
#: episode moves the channel to the next one. The text is added to the
#: creator's instructions for that night (and stored with them on the project).
FORMAT_ROTATION: Dict[str, List[Tuple[str, str]]] = {
    "Raat3Baje": [
        ("rules", "Tonight's format: a 'RULES' HORROR episode, planned exactly as the channel guide's "
                  "\"'Rules' horror in a long video\" section. Pure story from start to finish: no investigation, "
                  "research segment, folklore or cultural analysis, and nothing after the story's last line."),
        ("real_encounter", "Tonight's format: a REAL HORROR ENCOUNTER TOLD AS A STORY, planned exactly as the channel "
                           "guide's \"Real horror encounters, told as a story\" section. Built on one (or two or three, on "
                           "one theme) real first-hand accounts the researcher finds and cites -- a news report, a book of "
                           "collected accounts, an interview, a forum, Reddit or Quora post by the person it happened to "
                           "-- with the reported core kept exactly as reported. Told in the creator's own storytelling "
                           "voice, opened with one line saying whose experience it is and where it was shared. Pure story: "
                           "no investigation, no 'kya ye sach hai', and nothing after the story's last line."),
        ("story", "Tonight's format: a FICTIONAL HORROR STORY episode (no rule list), planned exactly as the channel "
                  "guide's \"Fictional horror story in a long video\" section. Pure story from start to finish: no "
                  "investigation, research segment, folklore or cultural analysis, and nothing after the story's "
                  "last line."),
        ("black_magic", "Tonight's format: a BLACK MAGIC (KALA JADU) STORY, planned exactly as the channel guide's "
                        "\"Black magic and tantra stories\" section: an original story in the world of totke, cursed "
                        "objects and a ritual done in jealousy or revenge, built on the real beliefs the researcher "
                        "finds (the signs, the remedies, the days and the places). Pure story, no real how-to, no "
                        "mockery of any religion or community, and nothing after the story's last line."),
        ("tantra", "Tonight's format: a TANTRA STORY, planned exactly as the channel guide's \"Black magic and tantra "
                   "stories\" section: an original story of a tantrik, a shamshan sadhna at night, an aghori or a siddhi "
                   "that demands its price, built on the real beliefs the researcher finds. The horror comes from one "
                   "person's misuse of power, never from the tradition itself. Pure story, no real mantras or steps, "
                   "and nothing after the story's last line."),
    ],
    # Beyond3Baje (2026-10-23): the creator's "What If this happened to you?"
    # stories alternate with the channel's investigations. The direction names
    # the writer persona whose blueprint the script must follow.
    "Beyond3Baje": [
        ("what_if", "Tonight's format: a 'WHAT IF THIS HAPPENED TO YOU?' STORY, planned exactly as the channel guide's "
                    "\"What If stories\" section and written on the WhatIfWriter persona's blueprint: strict second "
                    "person (\"Aap\"), one impossible rule inside an everyday Indian night, the viewer's own logic "
                    "(phone, CCTV, calls, a hotel) defeated by it, proximity escalating from outside to behind you, "
                    "uncanny detail and never gore, a written ending decided before scene one, and a gut-punch final "
                    "line with nothing after it. The uncanny mechanic may come from anywhere in the world; the setting "
                    "is the viewer's own. Present it as a story, never as an alleged real incident. The script's length "
                    "is the project's target runtime: scale the beats to it (a 5-minute script has about five beats of "
                    "two to five scenes each; a 20-minute one adds nights, witnesses and a second rule), never pad."),
        ("anomaly_file", "Tonight's format: an ANOMALY FILE, planned exactly as the channel guide's \"The Anomaly Files "
                         "(SCP-style)\" section and written on the WhatIfWriter persona's anomaly-file blueprint: an "
                         "ORIGINAL anomaly in India told as a containment report read aloud -- item number, class, "
                         "containment procedures, description, discovery log, incident logs in order, and one redacted "
                         "line whose content is the twist. The SCP wiki inspires the form only: no entry, name, number "
                         "or text from it is used. Scale the logs to the project's target runtime."),
        ("investigation", "Tonight's format: one of the channel's INVESTIGATIONS (an entity file, an encounter file, a "
                          "paranormal case file, a haunted location or an international urban legend), planned exactly "
                          "as the channel guide's pillars describe: subjects outside India, what was claimed against "
                          "what is documented, told as a friend investigating a strange story late at night."),
    ],
    # TheTallStoryteller (2026-10-23): a narrated storytelling channel of every
    # genre, rotating through all ten so no single genre takes over its feed.
    # TheTallStoryteller (creator, 2026-10-24): "mostly comedy and detective and
    # sometimes crime stories" -- no horror. FORMAT_TURNS below weights them.
    "TheTallStoryteller": [
        ("detective", "Tonight's format: a DETECTIVE story -- an original case solved by a sharp narrator-detective "
                      "through clues the viewer sees too (a theft, a disappearance, a murder, a fake haunting exposed "
                      "as a human trick), fair-play: every clue planted before the reveal, planned with the channel's "
                      "hook/setup/rising-stakes/turn/payoff shape. No supernatural answer, no horror tone."),
        ("comedy", "Tonight's format: COMEDY, an original light story in an Indian everyday world that escalates a "
                   "misunderstanding, a lie, a scheme or a small disaster to a satisfying, funny payoff, planned with "
                   "the channel's episode structure. Jokes from character and situation; no horror at all."),
        ("crime", "Tonight's format: a CRIME story -- a grounded heist, con, cover-up or chase told from the inside, "
                  "human motives and a turn the listener did not see coming, planned with the channel's episode "
                  "structure. No gore, no how-to for a real crime, no horror."),
    ],
}

#: How each format reads in the UI.
#: A channel whose formats are not taken equally: the order the turns go in, by key.
FORMAT_TURNS: Dict[str, List[str]] = {
    "TheTallStoryteller": ["detective", "comedy", "detective", "comedy", "crime"],
}

FORMAT_LABELS: Dict[str, str] = {
    "rules": "Rules horror", "real_encounter": "Real encounter, told as a story", "story": "Fictional horror story",
    "black_magic": "Black magic (kala jadu) story", "tantra": "Tantra story",
    "what_if": "What If... (second-person horror story)", "anomaly_file": "Anomaly file (SCP-style report)",
    "investigation": "Investigation (entity, encounter, case, location, legend)",
    "detective": "Detective", "folk_tale": "Folk tale", "mystery": "Mystery", "thriller": "Thriller", "history": "History",
    "mythology": "Mythology", "adventure": "Adventure", "emotional": "Emotional / drama",
    "classic_retold": "Classic literature, retold", "comedy": "Comedy", "horror_tale": "Horror (occasional)", "crime": "Crime",
}


def formats_for(channel: str) -> List[Dict[str, str]]:
    """The channel's episode formats, in rotation order: [{key, label, direction}]."""
    return [{"key": key, "label": FORMAT_LABELS.get(key, key), "direction": text}
            for key, text in FORMAT_ROTATION.get(channel, [])]


def format_direction(channel: str, key: Optional[str]) -> str:
    """A format's direction for the writer and the researcher, or ''."""
    from app.services.writing_style import canonical_channel
    return dict(FORMAT_ROTATION.get(canonical_channel(channel), [])).get(str(key or ""), "")


def _pinned_format(channel: str) -> Optional[str]:
    """The format the creator picked for the next episode (Long-form panel), if any."""
    try:
        from integrations.llm import load_config
        pin = (load_config().get("longform_next_format") or {}).get(channel)
    except Exception:  # noqa: BLE001
        return None
    return pin if pin in dict(FORMAT_ROTATION.get(channel, [])) else None


def set_pinned_format(channel: str, key: Optional[str]) -> None:
    from integrations.llm import load_config, save_config
    cfg = load_config()
    pins = dict(cfg.get("longform_next_format") or {})
    if key and key in dict(FORMAT_ROTATION.get(channel, [])):
        pins[channel] = key
    else:
        pins.pop(channel, None)
    cfg["longform_next_format"] = pins
    save_config(cfg)


def _locked_format(channel: str) -> Optional[str]:
    """The format the creator locked for every episode of this channel, if any."""
    try:
        from integrations.llm import load_config
        lock = (load_config().get("longform_format_lock") or {}).get(channel)
    except Exception:  # noqa: BLE001
        return None
    return lock if lock in dict(FORMAT_ROTATION.get(channel, [])) else None


def set_locked_format(channel: str, key: Optional[str]) -> None:
    from integrations.llm import load_config, save_config
    cfg = load_config()
    locks = dict(cfg.get("longform_format_lock") or {})
    if key and key in dict(FORMAT_ROTATION.get(channel, [])):
        locks[channel] = key
    else:
        locks.pop(channel, None)
    cfg["longform_format_lock"] = locks
    save_config(cfg)


def next_format(channel: str, offset: int = 0) -> Optional[Tuple[str, str]]:
    """The format for this channel's next episode (`offset` more slots ahead
    within one run): the one the creator pinned for it, else the one after
    the last episode actually built."""
    rotation = FORMAT_ROTATION.get(channel)
    if not rotation:
        return None
    names = [name for name, _ in rotation]
    locked = _locked_format(channel)
    if locked:  # locked for every episode: ignores the offset and the rotation
        return rotation[names.index(locked)]
    pinned = _pinned_format(channel)
    turns = [t for t in FORMAT_TURNS.get(channel, []) if t in names]
    if turns:
        # A weighted turn repeats keys, so the place in it is how many episodes the
        # channel has had (a pin starts the turn at that format instead).
        if pinned:
            start = turns.index(pinned) if pinned in turns else 0
            key = pinned if offset == 0 else turns[(start + offset) % len(turns)]
        else:
            done = sum(1 for run_ in _read_record().get("history", []) for b in run_.get("built", [])
                       if b.get("channel") == channel and b.get("format") in names)
            key = turns[(done + offset) % len(turns)]
        return rotation[names.index(key)]
    if pinned:
        start = names.index(pinned)  # the pinned format first, the rotation on from it
    else:
        last = None
        for run_ in _read_record().get("history", []):  # newest first
            # The last one that run built (a run builds them in rotation order).
            last = next((b.get("format") for b in reversed(run_.get("built", []))
                         if b.get("channel") == channel and b.get("format") in names), None)
            if last:
                break
        start = names.index(last) + 1 if last else 0
    return rotation[(start + offset) % len(rotation)]


def _instructions(raw: Any) -> Dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    return {ch: str(raw.get(ch) or "") for ch in WORKFLOWS}


def settings() -> Dict[str, Any]:
    from integrations.llm import load_config
    cfg = load_config()
    channels = cfg.get("longform_nightly_channels") or DEFAULT_CHANNELS
    return {
        "enabled": bool(cfg.get("longform_nightly_enabled", True)),
        "channels": [c for c in channels if c in WORKFLOWS],
        "per_channel": max(1, int(cfg.get("longform_nightly_per_channel", 1))),
        "minutes": _minutes(cfg.get("longform_nightly_minutes")),
        "instructions": _instructions(cfg.get("longform_nightly_instructions")),
        "last_run": _read_record().get("last_run", ""),
    }



# --- live status (read by the Projects -> Long-form panel) -------------------------

class Status:
    """The run's state in knowledge/nightly/longform_status.json, rewritten on
    every change so another process (the Studio, while the nightly run works)
    can show it."""

    MAX_LOG = 300

    def __init__(self, channels: List[str], per_channel: int, trigger: str):
        now = datetime.now().isoformat(timespec="seconds")
        self.data: Dict[str, Any] = {
            "state": "running", "trigger": trigger, "started_at": now, "updated_at": now, "finished_at": None,
            "error": None,
            "tasks": [{"channel": ch, "slot": i + 1, "stage": "queued", "topic": None, "project_id": None,
                       "detail": ""} for ch in channels for i in range(per_channel)],
            "log": [],
        }
        self._save()

    def task(self, channel: str, slot: int) -> Dict[str, Any]:
        return next(t for t in self.data["tasks"] if t["channel"] == channel and t["slot"] == slot)

    def set(self, channel: str, slot: int, **fields: Any) -> None:
        self.task(channel, slot).update(fields)
        self._save()

    def log(self, channel: str, text: str) -> None:
        logger.info("longform %s: %s", channel, text)
        self.data["log"].append({"at": datetime.now().strftime("%H:%M:%S"), "channel": channel, "text": text[:300]})
        self.data["log"] = self.data["log"][-self.MAX_LOG:]
        self._save()

    def finish(self, error: Optional[str] = None) -> None:
        self.data.update(state="failed" if error else "done", error=error,
                         finished_at=datetime.now().isoformat(timespec="seconds"))
        self._save()

    def _save(self) -> None:
        self.data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        path = status_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def status_path() -> str:
    return os.path.join(str(KNOWLEDGE_DIR), "nightly", "longform_status.json")


def read_status() -> Dict[str, Any]:
    try:
        with open(status_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"state": "idle", "tasks": [], "log": []}


# --- topics ------------------------------------------------------------------------

def _backlog(channel: str) -> List[Dict[str, Any]]:
    from app.services import topic_store
    rows = [t for t in topic_store.load_topics()
            if t.get("channel") == channel and (t.get("stage") or "backlog") in ("backlog", "potential")
            and str(t.get("topic") or "").strip()]
    # Best first: "potential" before "backlog", then viral potential, then oldest.
    rows.sort(key=lambda t: (t.get("stage") != "potential", -float(t.get("viral_potential") or 0),
                             t.get("saved_at") or ""))
    return rows


def _from_idea_dump(channel: str) -> List[Dict[str, Any]]:
    """The creator's own ideas (Research page -> Idea Dump), oldest first, that
    are not already in the vault. The one picked is promoted to the vault
    (the dump itself is never written), so it is not picked twice."""
    from app.services import topic_store
    try:
        with open(os.path.join(str(KNOWLEDGE_DIR), "idea_dump.json"), encoding="utf-8") as f:
            ideas = [d for d in json.load(f) if isinstance(d, dict)]
    except Exception:
        return []
    known = {str(t.get("topic") or "").strip().lower() for t in topic_store.load_topics()
             if t.get("channel") == channel}
    rows = [d for d in ideas if d.get("channel") == channel and str(d.get("title") or "").strip()
            and str(d["title"]).strip().lower() not in known]
    rows.sort(key=lambda d: d.get("createdAt") or "")
    return [{"topic": str(d["title"]).strip(), "channel": channel, "notes": d.get("notes") or "",
             "category": "General", "source_type": "idea_dump", "idea_dump_id": d.get("id")} for d in rows]


def _idea(idea_id: str, channel: str) -> Optional[Dict[str, Any]]:
    return next((i for i in _from_idea_dump(channel) if str(i.get("idea_dump_id")) == idea_id), None)


# --- the strategist's plan -----------------------------------------------------------

def strategist_for(channel: str) -> str:
    from app.services.studio_chat import strategist_for as lookup
    return lookup(channel)


FINAL_PLAN_SHAPE = (
    '[FINAL_PLAN]{"topic_ref": "vault:<id> | dump:<id> | new", '
    '"title": "working title, in the channel style", "angle": "one line", '
    '"brief": "a markdown creative brief for the researcher and the writer: the hook, the structure section by '
    'section with rough timings for the target length, the facts and sources that must be covered, tone and '
    'voice, what to avoid, and exact instructions for the script"}[/FINAL_PLAN]'
)


def _plan_task(channel: str, minutes: float, instructions: str, taken: List[str]) -> str:
    taken_l = {t.lower() for t in taken}
    vault = [t for t in _backlog(channel) if t["topic"].lower() not in taken_l][:25]
    dump = [i for i in _from_idea_dump(channel) if i["topic"].lower() not in taken_l][:25]
    lines = [
        f"Tonight you are planning ONE new long-form {channel} video, about {minutes:g} minutes long. "
        "The research and script steps run right after you, on your plan, and the creator reviews the script "
        "in the morning and records it.",
        "",
        "## The rules",
        f"The {channel} channel guide (in your system prompt) is the rule book for format, structure, tone, "
        "integrity and what to develop for every video. Follow it.",
        "",
        "## The creator's specific instructions for these runs -- these win over everything else",
        instructions.strip() or "(None right now: follow the channel guide.)",
        "",
        "## Candidate topics",
        "Topic Vault (approved by the creator, best first):",
        *([f"- [vault:{t['id']}] {t['topic']} (viral {t.get('viral_potential') or '?'})"
           + (f" -- {t['notes']}" if t.get("notes") else "") for t in vault] or ["- (empty)"]),
        "",
        f"Idea Dump (the creator's own ideas, oldest first; [IDEA_DUMP: {channel}] lists more):",
        *([f"- [dump:{i['idea_dump_id']}] {i['topic']}" for i in dump] or ["- (empty)"]),
    ]
    if taken:
        lines += ["", "Already planned tonight -- pick something different:", *[f"- {t}" for t in taken]]
    lines += [
        "",
        "## What to do",
        "1. Choose the single best topic for tonight. Prefer the creator's own topics (vault, then Idea Dump) "
        "unless the instructions say otherwise; propose a new one only if the instructions ask for it or none fit.",
        "2. Use your tools as much as the choice and the brief need: check the facts and sources, what already "
        "exists on YouTube, and hand parts to specialists (researchers, FactChecker, writers, TitleGenerator...). "
        "Check this channel's earlier episodes ([LIST_PROJECTS]) so the video connects to them.",
        "3. The brief must cover everything the channel guide says to develop for every video that belongs "
        "before the script (format, central question, research plan and sources, title options, thumbnail, hook, "
        "section-by-section structure, A-roll / camera / shot-list notes where the guide asks for them).",
        "4. Finish with:",
        FINAL_PLAN_SHAPE,
    ]
    return "\n".join(lines)


def plan(channel: str, minutes: float, instructions: str, taken: List[str],
         say: Callable[[str], None]) -> Dict[str, Any]:
    """The strategist's plan resolved to a topic row: {topic, plan, ...}.
    Raises if the strategist gave nothing usable."""
    from app.services import strategist_runner
    from app.services.studio_chat import channel_guide
    agent = strategist_for(channel)
    guide = channel_guide(channel, full=True)
    out = strategist_runner.run(
        agent, channel, _plan_task(channel, minutes, instructions, taken),
        system_extra=(f"\n\n## Channel guide: {channel}\n{guide}" if guide else ""), on_event=say)
    p = out["plan"]
    ref = str(p.get("topic_ref") or "new").strip()
    title = str(p.get("title") or "").strip()
    topic: Optional[Dict[str, Any]] = None
    if ref.startswith("vault:"):
        topic = next((t for t in _backlog(channel) if t.get("id") == ref[6:].strip()), None)
    elif ref.startswith("dump:"):
        topic = _idea(ref[5:].strip(), channel)
    if topic is None:
        if not title:
            raise RuntimeError(f"the plan named no usable topic ({ref})")
        topic = {"topic": title, "channel": channel, "category": "General", "source_type": "strategist",
                 "notes": str(p.get("angle") or "")}
    return {"topic": topic, "plan": p, "strategist": agent, "tool_calls": len(out["calls"])}


# --- building the project ------------------------------------------------------------

def _run_preproduction(project_id: str, say: Callable[[str], None],
                       on_step: Callable[[str], None] = lambda s: None) -> Any:
    from core.models.project import Project
    from runtime.workflow import WorkflowEngine
    engine = WorkflowEngine()
    project = Project.load(project_id)
    for _ in range(MAX_STEPS):
        if _needs_creator(project.current_step) or project.status == "completed":
            break
        on_step(project.current_step)
        say(f"step: {project.current_step}")
        project = engine.execute_next(project_id, allow_all=True)
        last = project.steps_history[-1] if project.steps_history else None
        if last and last.status == "failed":
            raise RuntimeError(f"step '{last.step_name}' failed")
    # Hand it back to the creator: later steps pause for approval again.
    project = Project.load(project_id)
    project.metadata["allow_all"] = False
    project.metadata["nightly_longform"] = {"built_at": datetime.now().isoformat(timespec="seconds")}
    project.save()
    return project



def continue_preproduction(project_id: str) -> None:
    """Carry a project built before 2026-10-24 (stopped at Visual Plan) on through the
    remaining planning steps, in the background, as the nightly run now does."""
    import threading
    from integrations import idle_offload

    def run() -> None:
        try:
            with idle_offload.busy():
                _run_preproduction(project_id, lambda m: logger.info("continue %s: %s", project_id, m))
        except Exception:  # noqa: BLE001 - recorded in the project's own step history
            logger.exception("continuing pre-production for %s failed", project_id)

    threading.Thread(target=run, name=f"longform-continue-{project_id}", daemon=True).start()

def build(channel: str, topic: Dict[str, Any], target_minutes: float, say: Callable[[str], None],
          plan: Optional[Dict[str, Any]] = None, instructions: str = "",
          on_step: Callable[[str], None] = lambda s: None, episode_format: str = "") -> Dict[str, Any]:
    from app.services import topic_store
    from executive.project import project_manager
    plan = plan or {}
    if not topic.get("id"):  # an Idea Dump idea or a new one: promote it to the vault first
        topic = topic_store.add_topic(topic, added_by="nightly", stage="backlog")
    name = str(plan.get("title") or topic["topic"]).strip()
    project = None
    for attempt in range(5):
        try:
            project = project_manager.create_project(
                name=name + (f" {attempt + 1}" if attempt else ""), brand=channel, workflow_name=WORKFLOWS[channel])
            break
        except ValueError:
            continue
    if project is None:
        raise RuntimeError("could not create a unique project id")
    project.metadata["target_duration_minutes"] = target_minutes
    project.metadata["topic_id"] = topic.get("id")
    if topic.get("notes"):
        project.metadata["topic_notes"] = topic["notes"]
    if instructions.strip():
        project.metadata["creator_instructions"] = instructions.strip()
    if episode_format:
        project.metadata["episode_format"] = episode_format
    # The medium the creator picked for this topic in the vault (real /
    # explainer / stick_figure / cartoon) becomes the project's own setting.
    from integrations.art_style import ART_STYLES
    if topic.get("art_style") in ART_STYLES and topic["art_style"] != "real":
        project.metadata["video_settings"] = {**(project.metadata.get("video_settings") or {}),
                                              "art_style": topic["art_style"]}
    brief = str(plan.get("brief") or "").strip()
    if brief:
        angle = str(plan.get("angle") or "").strip()
        project.metadata["creative_brief"] = (f"**Angle:** {angle}\n\n" if angle else "") + brief
        rel = "script/strategist_brief.md"
        with open(os.path.join(project.get_project_dir(), "script", "strategist_brief.md"), "w", encoding="utf-8") as f:
            f.write(f"# {name}\n\nTopic: {topic['topic']}\n\n{project.metadata['creative_brief']}\n")
        project.assets["strategist_brief"] = rel
    project.save()
    topic_store.update_topic(topic["id"], {"stage": "in_progress"})
    try:
        from app.services.events import bus
        bus.publish("project_created", {"project_id": project.id, "name": project.name, "brand": channel,
                                        "workflow_name": project.workflow_name, "current_step": project.current_step})
    except Exception:
        pass
    done = _run_preproduction(project.id, say, on_step)
    return {"channel": channel, "project_id": done.id, "title": done.name, "current_step": done.current_step}


def _fallback_topic(channel: str, taken: List[str]) -> Optional[Dict[str, Any]]:
    taken_l = {t.lower() for t in taken}
    for t in _backlog(channel) + _from_idea_dump(channel):
        if t["topic"].lower() not in taken_l:
            return t
    return None


def run(progress: Optional[Callable[[str], None]] = None, trigger: str = "nightly") -> Dict[str, Any]:
    s = settings()
    status = Status(s["channels"], s["per_channel"], trigger)
    built, skipped = [], []
    # The forecast and the pre-flight checks (app/services/run_forecast.py),
    # first thing in the log, so a night that cannot finish says so at once.
    try:
        from app.services import run_forecast
        fc = run_forecast.forecast()
        status.data["forecast"] = {"verdict": fc["verdict"], "deadline": fc["deadline"],
                                   "slots": [{k: x[k] for k in ("channel", "slot", "est_min", "end", "fits")}
                                             for x in fc["slots"]]}
        status.log("run", f"forecast: {fc['verdict']}")
        for check in run_forecast.preflight(fresh=True)["checks"]:
            if check["state"] in ("warn", "fail"):
                status.log("run", f"pre-flight {check['state']}: {check['label']}: {check['summary']}")
    except Exception as exc:  # noqa: BLE001 - the run goes on without them
        logger.warning("forecast/pre-flight skipped: %s", exc)
    try:
        for channel in s["channels"]:
            taken: List[str] = []
            built_here = 0
            for slot in range(1, s["per_channel"] + 1):
                # Master pause (docs/STUDIO_DIRECTOR_PLAN.md Part 1): hold
                # here, between slots, before the next one's strategist call
                # starts; the Story Desk steps it drives hold on their own
                # (app/services/master_control / runtime/workflow.py).
                from app.services import master_control
                master_control.wait_if_paused(f"longform_nightly: {channel} slot {slot}",
                                              lambda m, ch=channel: status.log(ch, m))
                # Fable review #9: minutes/instructions can change (Settings ->
                # Long form) while a multi-slot run is in progress; re-read
                # right before this slot's own plan/build, not just once at
                # the top of the run, so a later slot sees the change.
                minutes = settings()["minutes"].get(channel, s["minutes"].get(channel, DEFAULT_MINUTES))
                base_instructions = settings()["instructions"].get(channel, "")
                fmt = next_format(channel, built_here)
                instructions = "\n\n".join(x for x in (base_instructions.strip(), fmt[1] if fmt else "") if x)
                def say(m: str, ch: str = channel) -> None:
                    status.log(ch, m)
                    if progress:
                        progress(f"{ch}: {m}")
                status.set(channel, slot, stage="strategist planning", minutes=minutes)
                chosen: Optional[Dict[str, Any]] = None
                try:
                    chosen = plan(channel, minutes, instructions, taken, say)
                    say(f"plan: {chosen['plan'].get('title') or chosen['topic']['topic']} "
                        f"({chosen['tool_calls']} tool calls)")
                except Exception as exc:  # noqa: BLE001 - fall back to the creator's own list
                    say(f"strategist could not plan ({str(exc)[:160]}); using the top vault / Idea Dump topic")
                    topic = _fallback_topic(channel, taken)
                    if topic:
                        chosen = {"topic": topic, "plan": {}}
                if not chosen:
                    status.set(channel, slot, stage="skipped", detail="no topic in the vault or the Idea Dump")
                    skipped.append({"channel": channel, "reason": "no topic in the vault or the Idea Dump"})
                    continue
                taken.append(chosen["topic"]["topic"])
                status.set(channel, slot, topic=chosen["plan"].get("title") or chosen["topic"]["topic"])
                try:
                    result = build(channel, chosen["topic"], minutes, say, plan=chosen["plan"],
                                   instructions=instructions,
                                   on_step=lambda step, ch=channel, sl=slot: status.set(ch, sl, stage=step),
                                   episode_format=fmt[0] if fmt else "")
                    if fmt:
                        result["format"] = fmt[0]
                        built_here += 1
                    status.set(channel, slot, stage="done", project_id=result["project_id"],
                               detail=f"waiting at {result['current_step']}")
                    say(f"done: project ready at {result['current_step']}")
                    built.append(result)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Long-form build failed for %s", channel)
                    status.set(channel, slot, stage="failed", detail=str(exc)[:200])
                    say(f"failed: {str(exc)[:200]}")
                    skipped.append({"channel": channel, "topic": chosen["topic"].get("topic"),
                                    "reason": str(exc)[:200]})
            if built_here and _pinned_format(channel):
                # A pinned format is used once; the rotation goes on from it.
                set_pinned_format(channel, None)
    except Exception as exc:
        status.finish(str(exc)[:300])
        raise
    status.finish()
    record = {"last_run": datetime.now().date().isoformat(), "ran_at": datetime.now().isoformat(timespec="seconds"),
              "built": built, "skipped": skipped}
    history = _read_record().get("history", [])
    record["history"] = ([{k: record[k] for k in ("ran_at", "built", "skipped")}] + history)[:30]
    os.makedirs(os.path.dirname(_record_path()), exist_ok=True)
    with open(_record_path(), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return record


# --- "Run now" from the Projects page: one background run at a time ---------------

_job_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def running() -> bool:
    """A run in this process, or (per its lock) the nightly process."""
    if _thread is not None and _thread.is_alive():
        return True
    from integrations.nightly_task import time_limit_hours
    lock = os.path.join(str(KNOWLEDGE_DIR), "nightly", "running.lock")
    return os.path.exists(lock) and time.time() - os.path.getmtime(lock) < time_limit_hours() * 3600


def start_now() -> None:
    """Run the batch in a background thread (ignores `last_run`: an explicit
    run always runs). Raises RuntimeError if one is already going."""
    global _thread
    with _job_lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("A long-form run is already in progress.")
        if running():
            raise RuntimeError("The nightly run is in progress right now; it does the long-form batch itself.")

        def work() -> None:
            try:
                run(trigger="manual")
            except Exception:  # noqa: BLE001 - recorded in the status file
                logger.exception("Long-form run failed")

        _thread = threading.Thread(target=work, name="longform-run", daemon=True)
        _thread.start()
