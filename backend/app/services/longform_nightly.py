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
WORKFLOWS = {
    "Raat3Baje": "after_dark_narration",
    "Beyond3Baje": "beyond3baje_documentary",
    "Life3Baje": "life3baje_video",
}

#: The run stops once the project reaches this step: everything before it is
#: research and script, everything from it on wants the creator's review.
DEFAULT_MINUTES = 8.0

STOP_STEP = "Visual Plan"
MAX_STEPS = 4


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
        ("story", "Tonight's format: a FICTIONAL HORROR STORY episode (no rule list), planned exactly as the channel "
                  "guide's \"Fictional horror story in a long video\" section. Pure story from start to finish: no "
                  "investigation, research segment, folklore or cultural analysis, and nothing after the story's "
                  "last line."),
    ],
}


def next_format(channel: str, offset: int = 0) -> Optional[Tuple[str, str]]:
    """The format for this channel's next episode (`offset` more slots ahead
    within one run): the one after the last episode actually built."""
    rotation = FORMAT_ROTATION.get(channel)
    if not rotation:
        return None
    names = [name for name, _ in rotation]
    last = None
    for run_ in _read_record().get("history", []):  # newest first
        last = next((b.get("format") for b in run_.get("built", [])
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
        if project.current_step in (STOP_STEP, "Completed") or project.status == "completed":
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
    try:
        for channel in s["channels"]:
            base_instructions = s["instructions"].get(channel, "")
            taken: List[str] = []
            built_here = 0
            for slot in range(1, s["per_channel"] + 1):
                fmt = next_format(channel, built_here)
                instructions = "\n\n".join(x for x in (base_instructions.strip(), fmt[1] if fmt else "") if x)
                def say(m: str, ch: str = channel) -> None:
                    status.log(ch, m)
                    if progress:
                        progress(f"{ch}: {m}")
                status.set(channel, slot, stage="strategist planning")
                chosen: Optional[Dict[str, Any]] = None
                try:
                    chosen = plan(channel, s["minutes"][channel], instructions, taken, say)
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
                    result = build(channel, chosen["topic"], s["minutes"][channel], say, plan=chosen["plan"],
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
    lock = os.path.join(str(KNOWLEDGE_DIR), "nightly", "running.lock")
    return os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 4 * 3600


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
