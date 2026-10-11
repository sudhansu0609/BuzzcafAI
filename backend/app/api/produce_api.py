"""
The BuzzcafAI -> BuzzEdit video-production bridge (roadmap: BuzzEdit bridge).

BuzzcafAI's agents write a script and a structured per-scene `visual_plan.json`
(the "Visual Plan" workflow step, `runtime/workflow.py`); this router turns
those into a BuzzEdit-ready directive-annotated script and drives BuzzEdit's
own HTTP API end-to-end -- import the recording, transcribe it, set the
annotated script, enqueue a presentation-pass render, and poll it to done.

    POST /api/projects/{id}/produce_video {recording_path, settings_override?, mode?}
        Entry A (BuzzcafAI drives). Queues the run on the production queue
        (`app/services/produce_queue.py`), which runs one video at a time
        across every channel on its own worker thread. Fine-grained progress
        lives in the module-level `_produce_status` dict and on the SSE bus
        (`video_progress` / `video_ready` / `video_failed`).
    GET  /api/produce/queue, POST /api/produce/queue {project_id, recording_path, ...}
    POST /api/produce/queue/paused {paused}, /api/produce/queue/clear_finished
    POST /api/produce/queue/{item_id}/{pause|resume|cancel|retry|restart|move|remove}
        The queue itself. Pause/cancel are honoured at the checkpoints between
        stages; resume and retry pick up from the saved checkpoint.
    GET  /api/projects/{id}/produce_video/status
        Poll the run above.
    POST /api/produce/plan {brand, script_text?, transcript?}
        Entry B (BuzzEdit drives): a synchronous reverse endpoint BuzzEdit's
        own backend calls after it transcribes a recording, to get back an
        annotated script + settings + the raw visual plan.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services import produce_queue
from app.services.events import bus as event_bus
from core.config import config_manager
from core.models.project import Project
from core.paths import PROJECT_ROOT
from integrations.buzzedit_client import (BuzzEditClient, BuzzEditJobFailed, BuzzEditUnavailable,
                                          base_url as buzzedit_base_url)
from integrations.buzzedit_script import to_directive_script
from integrations import story_visuals
from integrations.buzzedit_settings import (
    DENSITIES,
    GENRES,
    InvalidChannelProfile,
    VISUAL_STYLES,
    brand_key,
    clean_auto_edit,
    fx_palette_for,
    get_channel_profile,
    is_story_style,
    list_channel_profiles,
    resolve_settings,
    runtime_mix,
    set_channel_profile,
    settings_for_brand,
)
from integrations.llm import (
    LLMService,
    claude_configured,
    claude_settings,
    load_config as load_llm_config,
    probe_claude,
    save_config as save_llm_config,
)
from integrations import sound_cues
from integrations.script_reconcile import Reconciliation, clean_spoken_script, extract_vocabulary, script_speakers
from integrations.visual_windows import (
    apply_prompt_edit,
    beats_per_minute_target,
    chunk_kept_words,
    plan_visual_windows,
    script_reference_section,
    workers_for,
)

#: Console children (PowerShell's file picker, the `lms` CLI, BuzzEdit's
#: launcher) must not flash a black cmd window over the Studio mid-render.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

#: Engines a project's `video_settings.music_engine` may name (BuzzEdit's music_gen.ENGINES).
MUSIC_ENGINES = ("ace_step", "stable_audio")
#: How several picked music tracks play (BuzzEdit's `music_tracks_mode`).
MUSIC_TRACK_MODES = ("together", "sequence")

#: The review modes a project's `video_settings.review_mode` may hold.
REVIEW_MODES = ("none", "plan", "cuts_and_plan")
#: The `produce_gate.stage` values a paused run may sit at, and the `stage`
#: a `produce_video/continue` call must name to resume it.
GATE_STAGES = ("cut_review", "plan_review", "effects_review")
#: Where the production queue resumes a run once its gate is continued.
_GATE_RESUME_POINT = {"cut_review": "plan", "plan_review": "finalize", "effects_review": "finalize"}
#: How long to wait for BuzzEdit's effects sample before giving up on it.
_EFFECTS_SAMPLE_TIMEOUT_SECONDS = 20 * 60

logger = logging.getLogger("buzzcaf_ai.produce_api")

router = APIRouter(tags=["Produce"])

# A project's live produce_video progress (the queue in
# app/services/produce_queue.py holds the durable part) lives here, keyed by BuzzcafAI project id, guarded by a
# lock since the background thread and the status-poll route both touch it.
_produce_status: Dict[str, Dict[str, Any]] = {}
_produce_lock = threading.Lock()

#: How often the poll loop checks BuzzEdit's job list.
_POLL_INTERVAL_SECONDS = 4.0
#: How often (in elapsed seconds) a `video_progress` SSE event is actually
#: published during the poll loop, so a multi-hour render does not flood the
#: event bus with one message every 4 seconds.
_PROGRESS_EVENT_EVERY_SECONDS = 30.0
#: A render is a one-GPU, minutes-per-clip job that can legitimately run for
#: hours. A fixed 3h cap gave up on a healthy render at 03:09 while BuzzEdit
#: kept going, so the wait now ends on a STALL: no change in the job's progress
#: or message for this long (a Wan clip times out in 15 min on BuzzEdit's side,
#: so an hour of silence means it is wedged). The absolute cap is a backstop.
_RENDER_STALL_SECONDS = 60 * 60
_MAX_RENDER_SECONDS = 24 * 60 * 60
#: While it generates B-roll on the GPU, BuzzEdit can be too busy to answer a
#: health probe or a job poll in time. That is not a failure: keep polling for
#: this long before giving up on an unreachable BuzzEdit mid-render.
_MAX_UNREACHABLE_SECONDS = 15 * 60
#: A job BuzzEdit answers about but does not list is gone; this is only grace
#: for a list caught mid-save.
_JOB_MISSING_SECONDS = 3 * 60


def _set_status(project_id: str, **fields: Any) -> None:
    with _produce_lock:
        current = dict(_produce_status.get(project_id) or {})
        current.update(fields)
        _produce_status[project_id] = current


def _get_status(project_id: str) -> Dict[str, Any]:
    with _produce_lock:
        return dict(_produce_status.get(project_id) or {"state": "idle"})


def render_in_progress() -> bool:
    """Whether any project has a produce_video run going -- the Studio holds
    off loading local LLMs onto the GPU while ComfyUI is rendering."""
    with _produce_lock:
        return any(s.get("state") in ("starting", "running") for s in _produce_status.values())


def buzzedit_job_active() -> bool:
    """Whether BuzzEdit's scheduler is working a job right now, whoever
    started it. The Studio's own status is not enough: a run the Studio lost
    track of (marked failed while BuzzEdit kept going) still owns the GPU --
    loading an LLM beside it timed out ComfyUI and cost 52 B-roll assets.

    Unknown counts as busy when BuzzEdit is up but slow to answer, since a
    render hogging the GPU is exactly when it misses short requests."""
    client = BuzzEditClient()
    try:
        if client.get_jobs().get("current_job_id"):
            return True
    except BuzzEditUnavailable:
        return buzzedit_base_url() is not None
    except Exception:  # noqa: BLE001 - a malformed answer must not block loading forever
        return False
    # A transcription is not a scheduler job, but it holds the GPU just the
    # same -- and runs its own Gemma passes through LM Studio. Unloading LM
    # Studio under one ("Model unloaded by user or API request") is what
    # the end-of-task offload did while BuzzEdit was still cutting.
    try:
        return bool(client.transcription_jobs())
    except Exception:  # noqa: BLE001 - an older BuzzEdit, or a slow one: not a reason to block
        return False


def _has_script_first_assets(project: Project) -> bool:
    return bool(project.assets.get("script")) and bool(project.assets.get("visual_plan"))


# ----------------------------------------------------------------------------
# Which model plans the video, and where the stock footage comes from.
#
# Settings -> "Claude API" holds the claude-local-api proxy (../claudeAPI) and
# a "Use Claude for video production" switch. When it is on, every model call
# produce_video makes -- the per-window visual planning here, and BuzzEdit's
# own moods / topics / thumbnail-title / picture-prompt passes -- goes to
# Claude instead of the local LM Studio model, which is what turned "Planning
# visuals" and "Reading the mood of each part" from minutes into seconds.
# ----------------------------------------------------------------------------


def produce_llm_provider() -> Optional[str]:
    """`"claude"` when production is routed through the Claude proxy and a key
    is saved, else None (the normal tier / selected-provider order)."""
    cfg = load_llm_config()
    if str(cfg.get("produce_llm_provider") or "auto").strip().lower() == "claude" and claude_configured(cfg):
        return "claude"
    return None


def produce_llm_service() -> LLMService:
    """An LLMService for produce_video's own calls: Claude first when routed
    there, falling back through the usual order if the proxy is down.

    With the switch on "auto" and a proxy key saved, Claude is still in the
    chain -- after the local model, as the fallback. Every visual-planning
    window of two productions failed as "simulated output (no provider
    reachable)" while the proxy sat idle next door, because Strict Local
    drops every non-local provider it was not asked for by name."""
    forced = produce_llm_provider()
    fallback = "claude" if forced is None and claude_configured(load_llm_config()) else None
    return LLMService(forced_provider=forced, purpose="production", fallback_provider=fallback)


def sync_claude_key_to_buzzedit(client: Optional[BuzzEditClient] = None) -> Optional[Dict[str, Any]]:
    """Hand the Studio's Claude proxy key to BuzzEdit (`PUT /api/settings/
    auto_cut_editor`), which is the side that runs the AI cut editor during
    transcription. Best-effort like the Pixabay sync: None when there is no
    key or BuzzEdit did not take it. Without this BuzzEdit's log reads "no key
    for the Claude proxy" and it falls back to the classic planner plus its
    slow local fluency/verify passes."""
    cfg = load_llm_config()
    if not claude_configured(cfg):
        return None
    claude = claude_settings(cfg)
    client = client or BuzzEditClient()
    try:
        return client.set_auto_cut_editor(claude["url"], claude["api_key"])
    except Exception as exc:  # noqa: BLE001 - a missing key costs the classic planner, not the cut
        logger.warning("Could not sync the Claude proxy key to BuzzEdit (%s).", exc)
        return None


def buzzedit_llm_settings() -> Dict[str, Any]:
    """Extra `PresentationSettings` fields telling BuzzEdit which model to run
    its planning passes on. Empty when production is not routed through
    Claude, so BuzzEdit keeps its own LM Studio default; an older BuzzEdit
    ignores the unknown fields."""
    if produce_llm_provider() != "claude":
        return {}
    cfg = claude_settings(load_llm_config())
    return {
        "llm_provider": "openai_compat",
        "llm_base_url": cfg["url"],
        "llm_api_key": cfg["api_key"],
        "llm_model": cfg["model"],
    }


#: The settings a running BuzzEdit pass re-reads (BuzzEdit presentation/live.py).
LIVE_SETTING_KEYS = ("target_coverage", "video_broll_share", "image_broll_share",
                     "broll_seconds_min", "broll_seconds_max")


def live_settings_for(settings: Dict[str, Any]) -> Dict[str, Any]:
    """The live subset of resolved settings, in BuzzEdit's terms: coverage is
    video + images of the running time, and the clip share is the clips' part
    of that coverage (what BuzzEdit's clip quota and re-balance measure),
    whatever the visual style -- a story plan's own clip kinds are what the
    live change overrides."""
    from integrations.buzzedit_settings import for_buzzedit
    converted = for_buzzedit(settings)
    out = {k: converted[k] for k in LIVE_SETTING_KEYS if converted.get(k) is not None}
    mix = runtime_mix(settings)
    if mix.get("mode") == "runtime":
        coverage = round(min(1.0, mix["video"] + mix["images"]), 3)
        out["target_coverage"] = coverage
        out["video_broll_share"] = round(mix["video"] / coverage, 3) if coverage else 0.0
        out["image_broll_share"] = mix["images"]
    return out


def production_rendering(project: Project) -> bool:
    """Whether this project's production is at the stage where BuzzEdit is
    generating or rendering (so a settings change can still reach it)."""
    item = produce_queue.active_item_for(project.id)
    if item and item.get("status") == "running" and item.get("checkpoint") in ("finalize", "render"):
        return True
    return bool(project.metadata.get("buzzedit_job_id")) and render_in_progress()


def push_live_settings(project: Project, client: Optional[BuzzEditClient] = None,
                       settings: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Hand the project's current mix to the BuzzEdit pass that is running
    (or about to run) for it -- the mid-production change. The creator moves
    the Video / Images sliders on the Projects page while clips are being
    generated; BuzzEdit stops promoting stills to clips once the new share is
    met and trims the cutaways to the new coverage before placing them. No
    restart, nothing already generated is lost. Best-effort: None when the
    project has no BuzzEdit project or BuzzEdit did not take it."""
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    if not buzzedit_project_id:
        return None
    if settings is None:
        settings, _ = resolve_settings(project.brand, None, project)
    overrides = live_settings_for(settings)
    if not overrides:
        return None
    client = client or BuzzEditClient()
    try:
        client.set_live_settings(buzzedit_project_id, overrides)
    except Exception as exc:  # noqa: BLE001 - the next pass still gets the saved settings
        logger.warning("produce_video(%s): BuzzEdit did not take the live settings (%s).", project.id, exc)
        return None
    logger.info("produce_video(%s): live settings sent to BuzzEdit: %s", project.id, overrides)
    return overrides


def stock_settings() -> Dict[str, Any]:
    """Settings -> "Stock footage (Pixabay)": the key and the on/off switch."""
    cfg = load_llm_config()
    key = str(cfg.get("pixabay_api_key") or os.environ.get("PIXABAY_API_KEY", "") or "").strip()
    return {"pixabay_enabled": bool(cfg.get("pixabay_enabled")), "pixabay_api_key": key}


def sync_stock_keys_to_buzzedit(client: Optional[BuzzEditClient] = None) -> Optional[Dict[str, Any]]:
    """Hand the Studio's Pixabay key to BuzzEdit (`PUT /api/settings/stock_keys`),
    which is the side that actually searches and downloads the footage.
    Best-effort: None when there is no key to send or BuzzEdit did not take
    it. Whether the key is *used* is `allow_free_stock` on the render job."""
    key = stock_settings()["pixabay_api_key"]
    if not key:
        return None
    client = client or BuzzEditClient()
    try:
        return client.set_stock_keys(pixabay_api_key=key)
    except Exception as exc:  # noqa: BLE001 - a missing stock key costs a fallback, not the render
        logger.warning("Could not sync the Pixabay key to BuzzEdit (%s).", exc)
        return None


def sync_thinking_to_buzzedit(client: Optional[BuzzEditClient] = None) -> None:
    """Settings -> Thinking -> video production also governs BuzzEdit's own
    local passes (moods, topics, picture prompts): its `llm_reasoning_effort`
    is "none" with thinking off, "medium" with it on. Best-effort."""
    effort = "medium" if load_llm_config().get("thinking_production", False) else "none"
    try:
        (client or BuzzEditClient()).set_app_settings({"llm_reasoning_effort": effort})
    except Exception as exc:  # noqa: BLE001 - BuzzEdit keeps its previous setting
        logger.warning("Could not sync the thinking setting to BuzzEdit (%s).", exc)


#: How BuzzEdit generates clips (`clip_generation_mode`, Projects page):
#: "classic" = 832x480, fast; "hq" = 1024x576 delivered at 1080p, slower.
CLIP_GENERATION_MODES = ("classic", "hq")


def clip_generation_mode() -> str:
    """The Studio's `clip_generation_mode`: "classic" unless set to "hq"."""
    mode = str(load_llm_config().get("clip_generation_mode") or "classic").strip().lower()
    return mode if mode in CLIP_GENERATION_MODES else "classic"


def sync_clip_generation_to_buzzedit(client: Optional[BuzzEditClient] = None) -> Optional[Dict[str, Any]]:
    """Hand the clip-generation mode to BuzzEdit (`PUT /api/settings/
    clip_generation`) before a production. Best-effort: None when BuzzEdit
    did not take it, and it keeps its previous mode."""
    mode = clip_generation_mode()
    try:
        return (client or BuzzEditClient()).set_clip_generation(mode)
    except Exception as exc:  # noqa: BLE001 - a missed mode costs the old generator, not the render
        logger.warning("Could not sync the clip generation mode (%s) to BuzzEdit (%s).", mode, exc)
        return None


def sfx_library_dirs() -> List[str]:
    """The Studio's saved `sfx_library_dirs` (Settings -> SFX library):
    folders of real-sound effects/beds BuzzEdit indexes for the SoundDesigner
    pass's cues to be matched against. [] when none are saved."""
    dirs = load_llm_config().get("sfx_library_dirs")
    if not isinstance(dirs, list):
        return []
    return [d.strip() for d in dirs if isinstance(d, str) and d.strip()]


def sync_sfx_library_to_buzzedit(client: Optional[BuzzEditClient] = None) -> Optional[Dict[str, Any]]:
    """Hand the saved SFX library folders to BuzzEdit (`PUT /api/sfx/library`)
    before a production. Best-effort: None when there is nothing saved or
    BuzzEdit did not take it, and it keeps whatever library it already has."""
    dirs = sfx_library_dirs()
    if not dirs:
        return None
    try:
        return (client or BuzzEditClient()).set_sfx_library(dirs)
    except Exception as exc:  # noqa: BLE001 - a missed sync costs the old library, not the render
        logger.warning("Could not sync the SFX library folders to BuzzEdit (%s).", exc)
        return None


def audio_rack_preset_for(brand: Optional[str]) -> Optional[str]:
    """The BuzzEdit audio rack preset the Studio's `audio_rack_preset` setting
    ({channel: preset name}, Projects page) names for this channel, or None
    (no entry, or a blank one). Channels match the way brands do (`brand_key`)."""
    table = load_llm_config().get("audio_rack_preset")
    if not brand or not isinstance(table, dict):
        return None
    key = brand_key(brand)
    for channel, name in table.items():
        if brand_key(str(channel)) == key and isinstance(name, str) and name.strip():
            return name.strip()
    return None


def apply_audio_rack_to_buzzedit(project: Project, client: BuzzEditClient,
                                 buzzedit_project_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Before a render: the BuzzEdit project's A1 rack becomes the channel's
    rack preset, and `audio_rack_used` ({audio_rack_preset, scope, effects})
    goes on the project and into the run's status for the report. Best-effort,
    like the clip-generation push: with no preset, no BuzzEdit project, or
    BuzzEdit not taking it, the render keeps the rack it has and nothing is
    recorded."""
    name = audio_rack_preset_for(project.brand)
    used: Optional[Dict[str, Any]] = None
    if name and buzzedit_project_id:
        rack = client.apply_rack_preset(buzzedit_project_id, "A1", name)
        if rack is not None:
            used = {"audio_rack_preset": name, "scope": "A1",
                    "effects": [str(e.get("effect")) for e in rack.get("effects") or [] if isinstance(e, dict)]}
            logger.info("produce_video(%s): audio rack preset %r on A1: %s.", project.id, name, used["effects"])
    fresh = Project.load(project.id)
    if used:
        fresh.metadata["audio_rack_used"] = used
    else:
        fresh.metadata.pop("audio_rack_used", None)
    fresh.save()
    _set_status(project.id, audio_rack_used=used)
    return used


# ───────────────────────────── Character voices ─────────────────────────────
# BuzzEdit's voice conversion driven from the Studio (BuzzEdit VOICE_CHANGER_PLAN.md
# brief S3): a story character in the cast sheet may have a voice; before the
# render the production sends BuzzEdit a voice map for the characters who speak
# labelled lines, BuzzEdit converts those lines, and the creator's narration
# stays his own.

#: The report's notes when nothing was converted.
VOICE_NOTE_NO_LIBRARY = "no voices in the library"
VOICE_NOTE_NO_CHARACTER_LINES = "script has no character lines"
VOICE_NOTE_NO_VOICE = "no character has a voice"


def _cast_speakers(project: Project) -> List[str]:
    """The cast sheet's character names: whose upper-case `NAME:` lines in the
    script are their dialogue (`script_reconcile`). Empty without a cast."""
    try:
        return story_visuals.character_names(story_visuals.load_cast_sheet(project))
    except Exception:  # noqa: BLE001 - the script still matches, just without them
        return []


def _voice_report(**fields: Any) -> Dict[str, Any]:
    report: Dict[str, Any] = {"voice_map": {}, "voice_conversions": [], "failed_spans": [],
                              "note": None, "warnings": [], "proposed": {}}
    report.update(fields)
    return report


def _convert_character_voices(project: Project, client: BuzzEditClient, buzzedit_project_id: str,
                              cast: Dict[str, Any]) -> Dict[str, Any]:
    """The steps of `apply_voice_map_to_buzzedit`; returns the report."""
    voices = client.list_voices()
    if voices is None:
        return _voice_report(note="BuzzEdit did not list its voices library (not running, or an older BuzzEdit)")
    if not voices:
        return _voice_report(note=VOICE_NOTE_NO_LIBRARY)
    spans = client.speaker_spans(buzzedit_project_id)
    if spans is None:
        return _voice_report(note="BuzzEdit did not read the script's speakers (see the log)")
    speakers = [str(s) for s in spans.get("speakers") or [] if str(s or "").strip()]
    if not speakers:
        # A narration-format script ("my style"): the creator says every line.
        return _voice_report(note=VOICE_NOTE_NO_CHARACTER_LINES)
    report = _voice_report()
    if not story_visuals.voices_decided(cast):
        proposed = story_visuals.propose_voices(cast, voices, client.voice_presets() or {})
        chosen = {p["name"]: p["voice"] for p in proposed.get("characters") or [] if p.get("voice")}
        if chosen:
            cast = story_visuals.save_cast_sheet(project, proposed)
            report["proposed"] = chosen
            logger.info("produce_video(%s): voices proposed for the cast: %s.", project.id,
                        ", ".join(f"{name} -> {entry.get('preset') or entry.get('voice')}"
                                  for name, entry in chosen.items()))
    if not any(isinstance(p, dict) and p.get("voice") for p in cast.get("characters") or []):
        report["note"] = VOICE_NOTE_NO_VOICE
        return report
    voice_map, warnings = story_visuals.voice_map_for(cast, speakers)
    report["warnings"] = warnings
    if not voice_map:
        report["note"] = "no character with a voice speaks a line of their own"
        return report
    if client.put_voice_map(buzzedit_project_id, voice_map) is None:
        report["note"] = "BuzzEdit did not take the voice map (see the log)"
        return report
    report["voice_map"] = voice_map
    job_id = client.apply_voice_map(buzzedit_project_id)
    if not job_id:
        report["note"] = "BuzzEdit did not start the voice conversion (see the log)"
        return report

    def progress(fraction: float, message: str) -> None:
        _set_status(project.id, message=f"Converting the character voices in BuzzEdit "
                                        f"({int(round(fraction * 100))}%{': ' + message if message else ''})...")

    _set_status(project.id, message="Converting the character voices in BuzzEdit...", progress=0.37)
    logger.info("produce_video(%s): converting %s in BuzzEdit (job %s).", project.id,
                ", ".join(f"{s} -> {e.get('preset') or e.get('voice')}" for s, e in voice_map.items()), job_id)
    try:
        job = client.wait_job(buzzedit_project_id, job_id, timeout_s=None, progress_cb=progress)
    finally:
        # The seed-vc worker holds ~3 GB of VRAM until it idles out: free it
        # for the render (ECOSYSTEM.md: one heavy GPU tenant at a time).
        client.stop_voice_worker()
    if job is None:
        report["note"] = "BuzzEdit's voice conversion did not finish (see the log)"
        return report
    if job.get("status") != "completed":
        report["note"] = f"voice conversion failed: {job.get('error') or 'no detail given'}"
        return report
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    report["voice_conversions"] = [c for c in result.get("voice_conversions") or [] if isinstance(c, dict)]
    report["failed_spans"] = [f for f in result.get("failed_spans") or [] if isinstance(f, dict)]
    if not report["voice_conversions"]:
        report["note"] = str(result.get("message") or "no character line was converted")
    return report


def apply_voice_map_to_buzzedit(project: Project, client: BuzzEditClient,
                                buzzedit_project_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Before a render, after the script is on the edit: the story's character
    lines in their cast voices.

    For a project whose cast sheet has characters: BuzzEdit's voices library
    is read, the script's speakers come from `speaker_spans`, voices are
    proposed once from the library when none was ever set, the voice map
    {speaker as the script writes it -> voice} goes to BuzzEdit, its
    conversion job is followed to the end (no fixed timeout) and its worker
    stopped so the render has the GPU. `voice_report` ({voice_map,
    voice_conversions, failed_spans, note, warnings, proposed}), and
    `voice_map` / `voice_conversions` when there are any, go on the project
    and into the run's status. Best-effort: a failure is logged and noted,
    and the render goes on with the recorded voice. None (nothing recorded)
    when the project has no cast characters or no BuzzEdit edit."""
    cast = story_visuals.load_cast_sheet(project)
    report: Optional[Dict[str, Any]] = None
    if buzzedit_project_id and story_visuals.character_names(cast):
        try:
            report = _convert_character_voices(project, client, buzzedit_project_id, cast)
        except Exception as exc:  # noqa: BLE001 - the render goes on with the recorded voice
            logger.warning("produce_video(%s): voice conversion skipped (%s).", project.id, exc)
            report = _voice_report(note=f"voice conversion failed: {exc}")
        if report.get("note"):
            logger.info("produce_video(%s): character voices: %s.", project.id, report["note"])
        for warning in report.get("warnings") or []:
            logger.info("produce_video(%s): %s", project.id, warning)
    fresh = Project.load(project.id)
    for key in ("voice_report", "voice_map", "voice_conversions"):
        fresh.metadata.pop(key, None)
    if report is not None:
        fresh.metadata["voice_report"] = report
        if report["voice_map"]:
            fresh.metadata["voice_map"] = report["voice_map"]
        if report["voice_conversions"]:
            fresh.metadata["voice_conversions"] = report["voice_conversions"]
    fresh.save()
    _set_status(project.id, voice_report=report, voice_map=(report or {}).get("voice_map") or None,
                voice_conversions=(report or {}).get("voice_conversions") or None)
    return report


def _load_visual_plan(project: Project) -> Dict[str, Any]:
    """The script's pre-recording visual plan (`production/visual_plan.json`),
    or an empty one. A plan that is not JSON -- a workflow step that ran with
    no model answering saved canned prose there, and `json.loads` on it
    killed a production after 26 minutes of transcription -- is logged,
    surfaced as a warning and treated as "no script beats": the planner
    builds the visuals from the take itself anyway (recording-first)."""
    text = _read_project_text_asset(project, ["visual_plan"])
    if not text or not text.strip():
        return {"beats": []}
    from integrations.llm import clean_json_response
    candidate = clean_json_response(text)
    try:
        plan = json.loads(candidate)
    except ValueError:
        # Prose around a JSON object: take the outermost {...}.
        start, end = candidate.find("{"), candidate.rfind("}")
        plan = None
        if 0 <= start < end:
            try:
                plan = json.loads(candidate[start:end + 1])
            except ValueError:
                plan = None
        if plan is None:
            logger.warning("produce_video(%s): the project's visual plan is not JSON (starts %r); "
                           "planning from the take alone.", project.id, text.strip()[:80])
            _set_status(project.id, warning="The script's visual plan was not valid JSON and was ignored; "
                                            "visuals come from the recording alone.")
            return {"beats": []}
    if isinstance(plan, list):
        plan = {"beats": plan}
    if not isinstance(plan, dict):
        return {"beats": []}
    plan.setdefault("beats", [])
    if not isinstance(plan["beats"], list):
        plan["beats"] = []
    return plan


def _read_project_text_asset(project: Project, asset_names: list) -> Optional[str]:
    """The text of the first asset in `asset_names` that the project actually
    has on disk (e.g. prefer `script/final.md` over `script/draft.md`)."""
    for name in asset_names:
        rel_path = project.assets.get(name)
        if not rel_path:
            continue
        full_path = os.path.join(project.get_project_dir(), rel_path)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
    return None


class ProduceVideoSchema(BaseModel):
    recording_path: str
    settings_override: Optional[Dict[str, Any]] = None
    mode: Optional[str] = None  # "script_first" | "record_first" | None (auto)
    # The recording is already cut: BuzzEdit keeps every frame and only
    # dresses it (B-roll, cards, captions, sound, grade). None defers to the
    # project's saved `video_settings.precut`, then to False (auto-cut ON --
    # BuzzEdit also removes fumbles and long pauses) if the project has none.
    precut: Optional[bool] = None


def _resolve_precut(payload_precut: Optional[bool], project: Project) -> bool:
    """Request -> the project's saved `video_settings.precut` -> False (the
    new default: auto-cut ON, BuzzEdit also removes fumbles and long pauses)."""
    if payload_precut is not None:
        return payload_precut
    saved = (project.metadata.get("video_settings") or {}).get("precut")
    return bool(saved) if saved is not None else False


def _resolve_review_mode(project: Project) -> str:
    """The project's saved `video_settings.review_mode`, defaulting to "plan"
    (pause after visual planning, before the multi-hour render) rather than
    rendering straight through without a look."""
    saved = (project.metadata.get("video_settings") or {}).get("review_mode")
    return saved if saved in REVIEW_MODES else "plan"


def _save_gate(project: Project, stage: str, mode: str, settings_override: Optional[Dict[str, Any]],
                precut: bool) -> None:
    """Persist enough to resume this run on a fresh thread (and after a
    restart) without anything still living only in this thread's memory."""
    project.metadata["produce_gate"] = {
        "stage": stage, "mode": mode, "settings_override": settings_override, "precut": precut,
    }
    project.save()


def _clear_gate(project: Project) -> None:
    if project.metadata.pop("produce_gate", None) is not None:
        project.save()


#: `produce_video`'s "already running" guard, and what a stale in-memory
#: status (e.g. after a restart) is *not* allowed to silently mean idle.
_BUSY_STATES = ("queued", "starting", "running", "awaiting_cut_review", "awaiting_plan_review")


@router.post("/api/projects/{project_id}/produce_video")
def produce_video(project_id: str, payload: ProduceVideoSchema):
    try:
        project = Project.load(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.main import active_executions

    if project_id in active_executions or _get_status(project_id).get("state") in _BUSY_STATES \
            or project.metadata.get("produce_gate") or produce_queue.active_item_for(project_id):
        raise HTTPException(status_code=409, detail="This project already has work running or queued.")

    mode = payload.mode or ("script_first" if _has_script_first_assets(project) else "record_first")
    precut = _resolve_precut(payload.precut, project)
    if payload.recording_path and project.metadata.get("recording_path") != payload.recording_path:
        # Remembered so a later batch queue (or a reopened panel) can offer it.
        project.metadata["recording_path"] = payload.recording_path
        project.save()

    # Every run goes through the production queue: one video on the GPU at a
    # time, whichever channel it belongs to. An empty queue starts it at once.
    _set_status(project_id, state="queued", message="Waiting in the production queue...", progress=0.0,
                error=None, warning=None, planning=None)
    try:
        item = produce_queue.add(
            project_id, brand=project.brand, title=project.name, recording_path=payload.recording_path,
            settings_override=payload.settings_override, mode=mode, precut=precut,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "queued", "project_id": project_id, "mode": mode, "queue_item_id": item["id"]}


#: How a resume point reads in a message (same words as the queue panel).
_STAGE_WORDS = {"start": "import", "transcribe": "transcription", "plan": "visual planning",
                "finalize": "render hand-off", "render": "render"}


def _queue_message(item: Dict[str, Any]) -> Optional[str]:
    """The line the queue panel shows for an item that is not running."""
    stage = _STAGE_WORDS.get(item.get("resume_from") or "start", item.get("resume_from"))
    if item["status"] == "paused":
        return f"Paused. Resumes at {stage}."
    if item["status"] == "queued":
        return (f"Waiting in the production queue -- picks up at {stage}."
                if item.get("resume_from") not in (None, "start") else "Waiting in the production queue...")
    if item["status"] == "failed":
        return item.get("error") or "Failed."
    if item["status"] == "cancelled":
        return "Cancelled."
    return None


def _align_with_queue(status: Dict[str, Any], item: Dict[str, Any]) -> None:
    """Make the project's status say what its queue item says.

    The queue is the record of what is actually happening to a run; the
    in-memory status only describes the attempt this process last made. They
    drifted apart: a run the queue had retried or resumed still showed the
    earlier failure under the project, and after a Studio restart a failed run
    showed as idle. The queue's state wins; the live message and progress are
    kept while it is running, since they are the more detailed of the two.
    """
    status["queue_item"] = item
    q = item["status"]
    live = status.get("state")
    if q in ("done", "failed", "cancelled") and (
            live in ("starting", "running") or str(live or "").startswith("awaiting_")):
        return  # a newer run than this finished item is under way
    if q == "running":
        if live not in ("starting", "running"):
            status.update(state="running", message=item.get("message") or "Working...", error=None)
    elif q == "awaiting_review":
        pass  # the live gate, or the persisted one restored below, says which review
    elif q in ("queued", "paused", "cancelled"):
        status.update(state=q, message=_queue_message(item), error=None)
    elif q == "failed":
        status.update(state="failed", error=item.get("error") or status.get("error") or "Failed.",
                      message=_queue_message(item))
    elif q == "done" and live not in ("ready",):
        status.update(state="ready", message="Video ready.", progress=1.0, error=None)


@router.get("/api/projects/{project_id}/produce_video/estimate")
def produce_video_estimate(project_id: str):
    """Inputs for the clip / time estimate under the Video / Images sliders:
    the running time to plan for and the machine's measured speeds. The page
    multiplies them out live as the sliders move."""
    from integrations import production_estimate as pe

    try:
        project = Project.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"runtime": pe.runtime_for(project), "speeds": pe.measured_speeds(),
            "clip_seconds": pe.CLIP_SECONDS, "still_seconds": pe.STILL_SECONDS}


@router.get("/api/projects/{project_id}/produce_video/status")
def produce_video_status(project_id: str):
    """The in-process status, or -- if this process was restarted since the
    run paused at a review gate, so `_produce_status` came back empty -- the
    gate persisted on the project itself, so the creator does not see a false
    "idle" for a run that is really just waiting on them."""
    status = _get_status(project_id)
    item = produce_queue.latest_item_for(project_id)
    if item:
        _align_with_queue(status, item)
    if status.get("state") == "idle":
        try:
            project = Project.load(project_id)
        except (ValueError, FileNotFoundError):
            return status
        gate = project.metadata.get("produce_gate")
        if gate and gate.get("stage") in GATE_STAGES:
            stage = gate["stage"]
            state = f"awaiting_{stage}"
            message = {
                "cut_review": "A review gate is still pending. Open BuzzEdit's Cuts view to review the auto-cut, then continue.",
                "plan_review": "A visual plan is still pending review. Continue below.",
                "effects_review": "An effects sample is waiting for your review. Continue below.",
            }[stage]
            restored = {"state": state, "message": message, "progress": None, "stage": stage,
                        "resumed_after_restart": True}
            if stage == "effects_review":
                restored["effects_sample"] = project.metadata.get("effects_sample")
            return restored
    return status


# ───────────────────────────────── Audio racks ─────────────────────────────────
# BuzzEdit's whole-rack audio presets (BuzzEdit AUDIO_SUITE_PLAN.md brief A5):
# the Projects page's per-channel "Audio rack" select and Dexter's audio actions.


class ApplyAudioRackSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


@router.get("/api/produce/audio_rack_presets")
def audio_rack_presets():
    """BuzzEdit's rack presets ({name: {effects, created, note}}) and the
    Studio's channel -> preset table. `available` is False when BuzzEdit did
    not answer."""
    presets = BuzzEditClient().list_rack_presets()
    table = load_llm_config().get("audio_rack_preset")
    return {"available": presets is not None, "presets": presets or {},
            "channels": table if isinstance(table, dict) else {}}


def _project_and_edit(project_id: str) -> Tuple[Project, Optional[str]]:
    try:
        project = Project.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Project not found")
    return project, project.metadata.get("buzzedit_project_id")


@router.get("/api/projects/{project_id}/audio_rack")
def project_audio_rack(project_id: str):
    """The audio racks of the project's BuzzEdit edit as BuzzEdit holds them
    now (`racks`, None without an edit or when BuzzEdit did not answer), the
    channel's preset, and `audio_rack_used` -- what the last production put
    on A1 before its render."""
    project, buzzedit_project_id = _project_and_edit(project_id)
    racks = None
    if buzzedit_project_id:
        try:
            data = BuzzEditClient().get_project(buzzedit_project_id) or {}
            raw = (data.get("timeline") or {}).get("audio_racks")
            racks = raw if isinstance(raw, dict) else {}
        except Exception as exc:  # noqa: BLE001 - a read: the Studio's side still answers
            logger.warning("Could not read the audio racks of BuzzEdit project %s (%s).", buzzedit_project_id, exc)
    return {"project_id": project.id, "channel": project.brand,
            "channel_preset": audio_rack_preset_for(project.brand),
            "audio_rack_used": project.metadata.get("audio_rack_used"),
            "buzzedit_project_id": buzzedit_project_id, "racks": racks}


@router.post("/api/projects/{project_id}/audio_rack/apply")
def apply_project_audio_rack(project_id: str, payload: ApplyAudioRackSchema):
    """The A1 (voice) rack of the project's BuzzEdit edit becomes a rack
    preset; the next render carries it. 409 without an edit, 502 when
    BuzzEdit did not take it."""
    project, buzzedit_project_id = _project_and_edit(project_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    if not buzzedit_project_id:
        raise HTTPException(status_code=409, detail="This project has no BuzzEdit edit yet: produce it first.")
    rack = BuzzEditClient().apply_rack_preset(buzzedit_project_id, "A1", name)
    if rack is None:
        raise HTTPException(status_code=502,
                            detail=f"BuzzEdit did not apply the rack preset {name!r} (not running, or no such preset).")
    return {"project_id": project.id, "buzzedit_project_id": buzzedit_project_id,
            "audio_rack_preset": name, **rack}


# ────────────────────────────── Character voices ──────────────────────────────
# The Projects page's cast block (a Voice select per character, Propose voices)
# and Dexter's voice actions. Voices live in BuzzEdit's library; deleting one
# is BuzzEdit's business, never offered here.


class CastVoiceSchema(BaseModel):
    character: str = Field(..., min_length=1, max_length=200)
    voice: Optional[str] = Field(None, max_length=200)
    preset: Optional[str] = Field(None, max_length=60)


@router.get("/api/produce/voices")
def voice_library():
    """BuzzEdit's voices library and voice presets. `available` is False when
    BuzzEdit did not answer."""
    client = BuzzEditClient()
    voices = client.list_voices()
    presets = client.voice_presets() if voices is not None else None
    return {"available": voices is not None, "voices": voices or [],
            "presets": (presets or {}).get("presets") or {},
            "engine_defaults": (presets or {}).get("engine_defaults") or {}}


def _cast_view(project: Project, cast: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cast = story_visuals.load_cast_sheet(project) if cast is None else cast
    characters = [{"name": p.get("name"), "gender": p.get("gender"), "look": p.get("look"),
                   "voice": p.get("voice"), "voice_set": "voice" in p}
                  for p in cast.get("characters") or [] if isinstance(p, dict) and p.get("name")]
    return {"project_id": project.id, "channel": project.brand, "characters": characters,
            "main_character": cast.get("main_character") or "",
            "voices_decided": story_visuals.voices_decided(cast),
            "buzzedit_project_id": project.metadata.get("buzzedit_project_id"),
            "voice_conversions": project.metadata.get("voice_conversions"),
            "voice_report": project.metadata.get("voice_report")}


def _cast_or_404(project: Project) -> Dict[str, Any]:
    cast = story_visuals.load_cast_sheet(project)
    if not story_visuals.character_names(cast):
        raise HTTPException(status_code=404,
                            detail="This project has no cast sheet yet: a story production writes it.")
    return cast


def _voice_entry(voice: Optional[str], preset: Optional[str]) -> Optional[Dict[str, Any]]:
    """A character's voice from a library voice and/or a preset, checked
    against BuzzEdit's library (a preset alone takes its own reference clip);
    None for neither (the creator's own voice)."""
    voice, preset = (voice or "").strip(), (preset or "").strip()
    if preset.lower() in ("custom", "none"):
        preset = ""
    if not voice and not preset:
        return None
    client = BuzzEditClient()
    library = client.list_voices()
    if library is None:
        raise HTTPException(status_code=502,
                            detail="BuzzEdit did not list its voices library (not running?), so the voice cannot be checked.")
    names = {str(v.get("name") or "").casefold(): str(v.get("name")) for v in library if v.get("name")}
    data = client.voice_presets() or {}
    defaults = data.get("engine_defaults") if isinstance(data.get("engine_defaults"), dict) else {}
    entry: Dict[str, Any] = {"voice": None, "preset": None,
                             "match_pitch": bool(defaults.get("f0_condition", False)),
                             "pitch_shift": defaults.get("pitch_shift", 0),
                             "steps": defaults.get("diffusion_steps", 25)}
    if preset:
        table = data.get("presets") if isinstance(data.get("presets"), dict) else {}
        name = next((n for n in table if n.casefold() == preset.casefold()), None)
        if name is None:
            raise HTTPException(status_code=422, detail=f"BuzzEdit has no voice preset {preset!r}.")
        params = table[name].get("params") if isinstance(table[name].get("params"), dict) else {}
        entry.update({"preset": name, **{k: params[k] for k in ("match_pitch", "pitch_shift", "steps") if k in params}})
        if not voice:
            stem = str(table[name].get("voice") or "")
            if stem.casefold() not in names:
                raise HTTPException(status_code=422,
                                    detail=f"The {name} preset's voice {stem!r} is not in BuzzEdit's voices library: "
                                           "add or record it there first.")
            voice = stem
    if voice.casefold() not in names:
        raise HTTPException(status_code=422, detail=f"No voice named {voice!r} in BuzzEdit's voices library.")
    entry["voice"] = names[voice.casefold()]
    return entry


@router.get("/api/projects/{project_id}/cast")
def project_cast(project_id: str):
    """The project's cast sheet (characters, looks, voices) and what the last
    production converted. `characters` is empty before a story production
    has written the sheet."""
    project, _ = _project_and_edit(project_id)
    return _cast_view(project)


@router.put("/api/projects/{project_id}/cast/voice")
def set_project_character_voice(project_id: str, payload: CastVoiceSchema):
    """One character's voice: a library voice, a preset (its reference from the
    library), both, or neither (the creator's own voice). The next production
    uses it. 404 no cast / no such character, 422 a voice or preset BuzzEdit
    does not have, 502 when BuzzEdit could not be asked."""
    project, _ = _project_and_edit(project_id)
    cast = _cast_or_404(project)
    entry = _voice_entry(payload.voice, payload.preset)
    try:
        cast = story_visuals.set_character_voice(cast, payload.character, entry)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No character named {payload.character!r} in the cast.")
    return _cast_view(project, story_visuals.save_cast_sheet(project, cast))


@router.post("/api/projects/{project_id}/cast/propose_voices")
def propose_project_voices(project_id: str):
    """Propose every character's voice from their description, with the voices
    BuzzEdit's library has (replaces the cast's voices; a character nothing
    fits keeps the creator's own). 404 no cast, 409 an empty library, 502
    BuzzEdit did not answer."""
    project, _ = _project_and_edit(project_id)
    cast = _cast_or_404(project)
    client = BuzzEditClient()
    voices = client.list_voices()
    if voices is None:
        raise HTTPException(status_code=502, detail="BuzzEdit did not list its voices library (not running?).")
    if not voices:
        raise HTTPException(status_code=409, detail="No voices in the library: add or record voices in BuzzEdit first.")
    stored = story_visuals.save_cast_sheet(project, story_visuals.propose_voices(cast, voices,
                                                                                  client.voice_presets() or {}))
    view = _cast_view(project, stored)
    view["proposed"] = {p["name"]: p["voice"] for p in view["characters"]}
    return view


@router.get("/api/projects/{project_id}/voice_map")
def project_voice_map(project_id: str):
    """Which character speaks in which voice: the cast's voices now (what the
    next production sends) and the voice map the last production sent
    BuzzEdit, keyed by the script's speakers."""
    project, buzzedit_project_id = _project_and_edit(project_id)
    cast = story_visuals.load_cast_sheet(project)
    return {"project_id": project.id, "buzzedit_project_id": buzzedit_project_id,
            "characters": {p["name"]: p.get("voice") for p in cast.get("characters") or []
                           if isinstance(p, dict) and p.get("name")},
            "last_voice_map": project.metadata.get("voice_map")}


@router.get("/api/projects/{project_id}/voice_conversions")
def project_voice_conversions(project_id: str):
    """What the last production converted (`[{speaker, voice, spans, seconds}]`)
    and its voice report (why nothing was, warnings, failed spans)."""
    project, buzzedit_project_id = _project_and_edit(project_id)
    return {"project_id": project.id, "buzzedit_project_id": buzzedit_project_id,
            "voice_conversions": project.metadata.get("voice_conversions") or [],
            "voice_map": project.metadata.get("voice_map"),
            "voice_report": project.metadata.get("voice_report")}


# ─────────────────────────────── Channel profiles ───────────────────────────────


class ChannelProfileSchema(BaseModel):
    genre: str
    genre_secondary: Optional[str] = None
    density: str
    voice_preset: Optional[str] = None
    # BuzzEdit auto-edit pacing for this channel; omitted = keep what is saved.
    auto_edit: Optional[Dict[str, Optional[float]]] = None


@router.get("/api/channel_profiles")
def get_channel_profiles():
    """Every brand's saved genre/density/voice-preset defaults -- the Studio
    Settings page's Channel Profiles section reads and edits these."""
    return {"profiles": list_channel_profiles(), "genres": list(GENRES), "densities": list(DENSITIES)}


@router.put("/api/channel_profiles/{brand}")
def put_channel_profile(brand: str, payload: ChannelProfileSchema):
    try:
        return set_channel_profile(brand, payload.model_dump(exclude_unset=True))
    except InvalidChannelProfile as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ──────────────────────────────── Video settings ────────────────────────────────


class MusicTrackSchema(BaseModel):
    """One track the creator picked from the music library, at a fixed level."""
    file: str = Field(..., min_length=1, max_length=300)   # relative to BuzzEdit's data/music
    volume_db: float = Field(-20.0, ge=-60.0, le=6.0)
    duck: bool = False                                      # pushed down under speech


class VideoSettingsSchema(BaseModel):
    visual_style: Optional[str] = None
    genre: Optional[str] = None
    genre_secondary: Optional[str] = None
    density: Optional[str] = None
    voice_preset: Optional[str] = None
    precut: Optional[bool] = None
    allow_free_stock: Optional[bool] = None
    target_coverage: Optional[float] = None
    video_broll_share: Optional[float] = None
    # Share of the running time that is still images (with video_broll_share as
    # the clips' share; the face gets the rest). Setting it switches a project
    # to the runtime mix -- see buzzedit_settings.runtime_mix.
    image_broll_share: Optional[float] = None
    broll_seconds_min: Optional[float] = None
    broll_seconds_max: Optional[float] = None
    min_oncamera_gap_s: Optional[float] = None
    zoom_depth: Optional[float] = None
    punch_rate_per_minute: Optional[float] = None
    text_fx_per_minute: Optional[float] = None
    # "none": render straight through. "plan": pause after visual planning so
    # the creator can review/edit the beats before the multi-hour render.
    # "cuts_and_plan": also pause right after the auto-cut, to review BuzzEdit's
    # cuts before anything is planned against them.
    review_mode: Optional[str] = None
    # Pause just before the render on a ~20 s effects sample of the real cut
    # (captions, knockout, text behind the head, a punch-in, SFX, music) so
    # the look can be checked -- and re-tested after a settings change --
    # in a couple of minutes rather than after the multi-hour render.
    effects_review: Optional[bool] = None
    # Background music: on/off, one brief for the whole video (BuzzEdit's cue
    # grammar, e.g. "sad solo violin, 70 bpm"), whether the script's
    # [music: ...] cues are followed, and the engine new tracks are made with.
    music: Optional[bool] = None
    music_brief: Optional[str] = None
    music_cues: Optional[bool] = None
    music_engine: Optional[str] = None
    # Tracks picked from the library, each at its own fixed level; when any is
    # set they replace the automatic music. "together" layers them under the
    # whole video, "sequence" plays them one after another, looping the list.
    music_tracks: Optional[List[MusicTrackSchema]] = None
    music_tracks_mode: Optional[str] = None


def _load_project_or_404(project_id: str) -> Project:
    try:
        return Project.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/api/projects/{project_id}/video_settings")
def get_video_settings(project_id: str):
    """This project's saved style overrides, plus the fully resolved
    (base -> density -> channel profile -> project) effective settings and
    which layer each field came from."""
    project = _load_project_or_404(project_id)
    settings, sources = resolve_settings(project.brand, None, project)
    return {
        "video_settings": project.metadata.get("video_settings") or {},
        "effective": settings,
        "sources": sources,
        # Video / images / face as shares of the running time (the sliders).
        "mix": runtime_mix(settings),
    }


@router.put("/api/projects/{project_id}/video_settings")
def put_video_settings(project_id: str, payload: VideoSettingsSchema):
    """Persist this project's style overrides (`project.metadata.video_settings`).
    A field sent as `null` clears that override, falling back to the channel
    profile/base again; a field left out of the payload entirely is untouched."""
    project = _load_project_or_404(project_id)
    provided = payload.model_dump(exclude_unset=True)

    genre = provided.get("genre")
    if genre is not None and genre not in GENRES:
        raise HTTPException(status_code=400, detail=f"Unknown genre: {genre!r}. Must be one of {', '.join(GENRES)}.")
    genre_secondary = provided.get("genre_secondary")
    if genre_secondary is not None and genre_secondary not in GENRES:
        raise HTTPException(status_code=400,
                             detail=f"Unknown genre_secondary: {genre_secondary!r}. Must be one of {', '.join(GENRES)}.")
    density = provided.get("density")
    if density is not None and density not in DENSITIES:
        raise HTTPException(status_code=400, detail=f"Unknown density: {density!r}. Must be one of {', '.join(DENSITIES)}.")
    visual_style = provided.get("visual_style")
    if visual_style is not None and visual_style not in VISUAL_STYLES:
        raise HTTPException(status_code=400,
                             detail=f"Unknown visual_style: {visual_style!r}. Must be one of {', '.join(VISUAL_STYLES)}.")
    review_mode = provided.get("review_mode")
    if review_mode is not None and review_mode not in REVIEW_MODES:
        raise HTTPException(status_code=400,
                             detail=f"Unknown review_mode: {review_mode!r}. Must be one of {', '.join(REVIEW_MODES)}.")

    music_engine = provided.get("music_engine")
    if music_engine is not None and music_engine not in MUSIC_ENGINES:
        raise HTTPException(status_code=400,
                             detail=f"Unknown music_engine: {music_engine!r}. Must be one of {', '.join(MUSIC_ENGINES)}.")
    mode = provided.get("music_tracks_mode")
    if mode is not None and mode not in MUSIC_TRACK_MODES:
        raise HTTPException(status_code=400,
                             detail=f"Unknown music_tracks_mode: {mode!r}. Must be one of {', '.join(MUSIC_TRACK_MODES)}.")
    if provided.get("music_tracks") is not None:
        tracks, seen = [], set()
        # Dumped again in full: exclude_unset would drop a track's default level.
        for track in (t.model_dump() for t in payload.music_tracks or []):
            path = track["file"].strip().replace("\\", "/").lstrip("/")
            if not path or ".." in path.split("/") or path.lower() in seen:
                continue
            seen.add(path.lower())
            tracks.append({**track, "file": path})
        provided["music_tracks"] = tracks
    if provided.get("music_brief") is not None:
        provided["music_brief"] = " ".join(str(provided["music_brief"]).split())[:300]

    for key in ("broll_seconds_min", "broll_seconds_max"):
        value = provided.get(key)
        if value is not None and not (1.0 <= float(value) <= 8.0):
            raise HTTPException(status_code=400, detail=f"{key} must be between 1 and 8 seconds.")

    video_settings = dict(project.metadata.get("video_settings") or {})
    for key, value in provided.items():
        if value is None:
            video_settings.pop(key, None)
        else:
            video_settings[key] = value
    lo, hi = video_settings.get("broll_seconds_min"), video_settings.get("broll_seconds_max")
    if lo is not None and hi is not None and float(lo) > float(hi):
        raise HTTPException(status_code=400, detail="broll_seconds_min cannot be longer than broll_seconds_max.")
    project.metadata["video_settings"] = video_settings
    project.save()

    settings, sources = resolve_settings(project.brand, None, project)
    live_applied = None
    if any(k in provided for k in LIVE_SETTING_KEYS) and production_rendering(project):
        live_applied = push_live_settings(project, settings=settings)
    return {"video_settings": video_settings, "effective": settings, "sources": sources,
            "mix": runtime_mix(settings), "live_applied": live_applied}


@router.post("/api/projects/{project_id}/live_settings")
def post_live_settings(project_id: str):
    """Send the project's saved mix to the BuzzEdit pass running for it now."""
    try:
        project = Project.load(project_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.metadata.get("buzzedit_project_id"):
        raise HTTPException(status_code=400, detail="This project has not been sent to BuzzEdit yet.")
    applied = push_live_settings(project)
    if applied is None:
        raise HTTPException(status_code=502, detail="BuzzEdit did not take the live settings (is it running?).")
    settings, _ = resolve_settings(project.brand, None, project)
    return {"live_applied": applied, "mix": runtime_mix(settings), "rendering": production_rendering(project)}


def get_buzzedit_dir() -> Optional[str]:
    """Find the BuzzEdit workspace directory."""
    configured = os.environ.get("BUZZEDIT_DIR") or config_manager.get("buzzedit_dir")
    if configured and os.path.isdir(configured):
        return configured

    candidate = os.path.abspath(os.path.join(PROJECT_ROOT.parent, "BuzzEdit"))
    if os.path.isdir(candidate):
        return candidate

    return None


#: A headless BuzzEdit that has not answered for this long since it started is
#: hung, not starting: it is stopped and a fresh one launched instead.
BUZZEDIT_STARTUP_GRACE_S = 180.0


def _headless_buzzedit_starting() -> bool:
    """A BuzzEdit the Studio started is already running but not answering yet.
    Launching another then gave two (the second on the next port), and only one
    was ever stopped when the Studio closed. One past its startup grace is hung:
    it is stopped here and False returned, so a fresh one is launched."""
    try:
        from app.services import process_cleanup

        roots = process_cleanup.headless_buzzedit_roots()
        if not roots:
            return False
        oldest = min(root.create_time() for root in roots)
        if time.time() - oldest < BUZZEDIT_STARTUP_GRACE_S:
            return True
        logger.warning("A headless BuzzEdit has not answered for %.0f s; stopping it and starting a fresh one.",
                       time.time() - oldest)
        process_cleanup.stop_headless_buzzedit()
    except Exception as exc:  # noqa: BLE001 - when unsure, launch as before
        logger.debug("Could not check for a starting BuzzEdit (%s).", exc)
    return False


def launch_buzzedit_process() -> bool:
    """Launch the BuzzEdit desktop app launcher silently."""
    buzzedit_dir = get_buzzedit_dir()
    if not buzzedit_dir:
        logger.warning("BuzzEdit directory not found; cannot auto-start.")
        return False
    if _headless_buzzedit_starting():
        logger.info("A BuzzEdit the Studio started is still coming up; waiting for it instead of starting another.")
        return True

    vbs = os.path.join(buzzedit_dir, "START_APP.vbs")
    bat = os.path.join(buzzedit_dir, "START_APP.bat")

    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                             | _NO_WINDOW)

        # A BuzzEdit we start is a background renderer, not something the
        # creator opened: its Electron window stays hidden (tray icon -> Show
        # brings it up). The variable travels launcher -> PowerShell -> Electron.
        env = dict(os.environ)
        env["BUZZEDIT_HEADLESS"] = "1"
        # From the desktop Studio, BuzzEdit watches this pid and quits (taking
        # its backend and ComfyUI) once the Studio is gone, however it ended.
        # Not from the nightly runner: its BuzzEdit jobs outlive that script.
        env.pop("BUZZCAF_STUDIO_PID", None)
        if env.get("BUZZCAF_DESKTOP_PID") == str(os.getpid()):
            env["BUZZCAF_STUDIO_PID"] = str(os.getpid())

        if os.path.exists(vbs) and sys.platform == "win32":
            logger.info("Auto-starting BuzzEdit (headless) via %s", vbs)
            subprocess.Popen(["wscript.exe", vbs], cwd=buzzedit_dir, shell=False,
                             creationflags=creationflags, env=env)
            return True
        elif os.path.exists(bat) and sys.platform == "win32":
            logger.info("Auto-starting BuzzEdit (headless) via %s", bat)
            subprocess.Popen(["cmd.exe", "/c", bat], cwd=buzzedit_dir,
                             creationflags=creationflags, env=env)
            return True
        else:
            logger.info("Auto-starting BuzzEdit (headless) via npm start in %s", buzzedit_dir)
            subprocess.Popen(["npm", "start"], cwd=buzzedit_dir, shell=True,
                             creationflags=creationflags, env=env)
            return True
    except Exception as exc:
        logger.error("Failed to launch BuzzEdit: %s", exc)
        return False


#: Whisper's language for every production: the channels are spoken in Hindi
#: (Hinglish). A channel profile may override it with a `language` key.
TRANSCRIBE_LANGUAGE = "hi"
#: How many times a BuzzEdit step (import, transcription) is attempted before
#: the run fails, and how long to wait between attempts.
BUZZEDIT_RETRY_ATTEMPTS = 3
BUZZEDIT_RETRY_BACKOFF_SECONDS = (30, 90)


def _with_buzzedit_retries(project_id: str, what: str, fn: Callable[[], Any],
                           status_cb: Optional[Callable[[str], None]] = None,
                           attempts: int = BUZZEDIT_RETRY_ATTEMPTS) -> Any:
    """Run `fn` against BuzzEdit, trying again when BuzzEdit went away (it is
    relaunched first) or reported the job failed. One bad answer used to end
    a production that had already spent an hour on eye contact and Whisper."""
    last: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (BuzzEditUnavailable, BuzzEditJobFailed, RuntimeError) as exc:
            last = exc
            if attempt >= attempts:
                raise
            wait = BUZZEDIT_RETRY_BACKOFF_SECONDS[min(attempt - 1, len(BUZZEDIT_RETRY_BACKOFF_SECONDS) - 1)]
            logger.warning("produce_video(%s): BuzzEdit %s attempt %d/%d failed (%s); retrying in %ds.",
                           project_id, what, attempt, attempts, exc, wait)
            if status_cb:
                status_cb(f"BuzzEdit {what} failed ({str(exc)[:160]}); retrying ({attempt + 1}/{attempts}) "
                          f"in {wait}s...")
            time.sleep(wait)
            if isinstance(exc, BuzzEditUnavailable):
                try:
                    ensure_buzzedit_running(
                        status_callback=(lambda msg, _p: status_cb(msg)) if status_cb else None, timeout=120.0)
                except BuzzEditUnavailable as relaunch_exc:
                    logger.warning("produce_video(%s): BuzzEdit did not come back (%s).", project_id, relaunch_exc)
    assert last is not None
    raise last


def ensure_buzzedit_running(status_callback: Optional[Callable[[str, float], None]] = None, timeout: float = 75.0) -> Dict[str, Any]:
    """Ensure BuzzEdit is running and reachable.
    If not running, attempts to launch it and waits for its health endpoint to answer."""
    client = BuzzEditClient()
    health = client.health()
    if health is not None:
        return health

    if status_callback:
        status_callback("BuzzEdit is not running. Launching BuzzEdit...", 0.02)

    launched = launch_buzzedit_process()
    if not launched:
        raise BuzzEditUnavailable(
            "BuzzEdit is not running and could not be found to auto-start. "
            "Please start BuzzEdit manually."
        )

    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(2.0)
        elapsed = int(time.time() - start_time)
        if status_callback:
            status_callback(f"Starting BuzzEdit... ({elapsed}s)", 0.03)
        health = client.health()
        if health is not None:
            logger.info("BuzzEdit answered health check after %ds", elapsed)
            break

    if health is None:
        raise BuzzEditUnavailable(
            f"BuzzEdit was launched but did not answer health check within {int(timeout)} seconds."
        )

    # Wait up to 35s for ComfyUI if not yet connected
    comfy_start = time.time()
    while not health.get("comfyui_connected") and time.time() - comfy_start < 35.0:
        time.sleep(2.5)
        if status_callback:
            status_callback("BuzzEdit is up. Waiting for ComfyUI to connect...", 0.04)
        health = client.health()
        if not health:
            break

    return health or {}


def pick_video_file() -> Optional[str]:
    """Open native file dialog on Windows to select a video file."""
    if sys.platform != "win32":
        return None

    # Try PowerShell OpenFileDialog with TopMost owner form
    ps_cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.OpenFileDialog; "
        "$d.Title = 'Select Video Recording'; "
        "$d.Filter = 'Video Files (*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v)|*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v|All Files (*.*)|*.*'; "
        "$f = New-Object System.Windows.Forms.Form; "
        "$f.TopMost = $true; "
        "if ($d.ShowDialog($f) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $d.FileName }"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=_NO_WINDOW,
        )
        selected = proc.stdout.strip()
        if selected and os.path.exists(selected):
            return selected
    except Exception as exc:
        logger.warning("PowerShell file dialog failed: %s", exc)

    # Fallback to Tkinter
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilename(
            title="Select Video Recording",
            filetypes=[
                ("Video Files", "*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v"),
                ("All Files", "*.*"),
            ],
        )
        root.destroy()
        if selected and os.path.exists(selected):
            return selected
    except Exception as exc:
        logger.warning("Tkinter file dialog failed: %s", exc)

    return None


_VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")


def pick_video_files() -> List[str]:
    """Native multi-select file dialog (Windows) -> the chosen video paths,
    in the order the dialog returns them. Empty when cancelled."""
    if sys.platform != "win32":
        return []
    ps_cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.OpenFileDialog; "
        "$d.Title = 'Select Video Recordings'; "
        "$d.Multiselect = $true; "
        "$d.Filter = 'Video Files (*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v)|*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v|All Files (*.*)|*.*'; "
        "$f = New-Object System.Windows.Forms.Form; "
        "$f.TopMost = $true; "
        "if ($d.ShowDialog($f) -eq [System.Windows.Forms.DialogResult]::OK) { $d.FileNames | ForEach-Object { Write-Output $_ } }"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=300, creationflags=_NO_WINDOW,
        )
        return [p for p in (line.strip() for line in proc.stdout.splitlines()) if p and os.path.exists(p)]
    except Exception as exc:
        logger.warning("PowerShell multi-file dialog failed: %s", exc)
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilenames(
            title="Select Video Recordings",
            filetypes=[("Video Files", " ".join("*" + e for e in _VIDEO_EXTENSIONS)), ("All Files", "*.*")],
        )
        root.destroy()
        return [p for p in selected if os.path.exists(p)]
    except Exception as exc:
        logger.warning("Tkinter multi-file dialog failed: %s", exc)
    return []


@router.post("/api/produce/browse_recordings")
def browse_recordings():
    """Multi-select file chooser for queueing several videos at once."""
    return {"paths": pick_video_files()}


@router.post("/api/produce/browse_recording")
def browse_recording():
    """Trigger a native file chooser dialog and return the selected video path."""
    path = pick_video_file()
    return {"path": path}


@router.get("/api/produce/buzzedit/status")
def buzzedit_status():
    """Check BuzzEdit and ComfyUI status."""
    client = BuzzEditClient()
    health = client.health()
    url = None
    try:
        url = buzzedit_base_url()
    except Exception:
        pass

    return {
        "online": health is not None,
        "comfyui_online": bool(health and health.get("comfyui_connected")),
        "url": url,
        "details": health,
    }


@router.get("/api/produce/claude/status")
def claude_status():
    """Is the Claude proxy (Settings -> Claude API) up, and does our key open
    it? Plus whether production is currently routed through it."""
    result = probe_claude()
    result["routed"] = produce_llm_provider() == "claude"
    return result


@router.get("/api/produce/stock/status")
def stock_status():
    """The Studio's Pixabay switch/key state, and (best-effort) which stock
    keys BuzzEdit itself currently holds, masked."""
    stock = stock_settings()
    buzzedit: Optional[Dict[str, Any]] = None
    try:
        buzzedit = BuzzEditClient().get_stock_keys()
    except Exception as exc:  # noqa: BLE001 - BuzzEdit being down is a normal state here
        logger.debug("stock_status: BuzzEdit stock keys unavailable (%s).", exc)
    return {
        "pixabay_enabled": stock["pixabay_enabled"],
        "pixabay_key_set": bool(stock["pixabay_api_key"]),
        "buzzedit": buzzedit,
    }


@router.post("/api/produce/stock/sync")
def stock_sync():
    """Push the saved Pixabay key to BuzzEdit now (it is also pushed before
    every render that has the stock fallback on)."""
    if not stock_settings()["pixabay_api_key"]:
        raise HTTPException(status_code=400, detail="No Pixabay API key is saved in Settings.")
    result = sync_stock_keys_to_buzzedit()
    if result is None:
        raise HTTPException(status_code=502, detail="BuzzEdit did not accept the key (is it running?).")
    return {"status": "synced", "buzzedit": result}


# ────────────────────────────────── SFX library ──────────────────────────────────
#
# Settings -> SFX library: the folders of real-sound effects/beds BuzzEdit
# indexes, pushed to it (best-effort, like the Pixabay key and clip-generation
# mode) before every production, plus a thin proxy onto BuzzEdit's own
# library/generate routes so the Studio UI never has to find BuzzEdit itself.


@router.get("/api/produce/sfx/library")
def get_sfx_library_route():
    """The Studio's saved SFX library folders, and (best-effort) BuzzEdit's
    own indexed summary of them -- None when BuzzEdit did not answer."""
    buzzedit = BuzzEditClient().get_sfx_library()
    return {"dirs": sfx_library_dirs(), "default": (buzzedit or {}).get("default") or [], "buzzedit": buzzedit}


class SfxLibrarySchema(BaseModel):
    dirs: List[str]


@router.put("/api/produce/sfx/library")
def put_sfx_library_route(payload: SfxLibrarySchema):
    """Save the Studio's SFX library folders and push them to BuzzEdit.

    BuzzEdit rejecting one or more folders (422) is surfaced as-is, with its
    own detail; BuzzEdit simply being unreachable is not an error here -- the
    folders are still saved, and the response's `buzzedit` comes back None."""
    dirs = [d.strip() for d in payload.dirs if isinstance(d, str) and d.strip()]
    new_config = load_llm_config()
    new_config["sfx_library_dirs"] = dirs
    save_llm_config(new_config)

    client = BuzzEditClient()
    try:
        resp = client._put("/api/sfx/library", {"dirs": dirs}, timeout=(5, 30))
    except Exception as exc:  # noqa: BLE001 - BuzzEdit offline costs the push, not the save
        logger.warning("Could not push the SFX library folders to BuzzEdit (%s).", exc)
        return {"dirs": dirs, "default": [], "buzzedit": None}
    if resp.status_code == 422:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text[:300]
        raise HTTPException(status_code=422, detail=detail or "BuzzEdit rejected one or more folders.")
    if resp.status_code >= 400:
        logger.warning("BuzzEdit refused the SFX library update: HTTP %s.", resp.status_code)
        return {"dirs": dirs, "default": [], "buzzedit": None}
    buzzedit = resp.json()
    return {"dirs": dirs, "default": (buzzedit or {}).get("default") or [], "buzzedit": buzzedit}


@router.post("/api/produce/sfx/library/refresh")
def refresh_sfx_library_route():
    """Ask BuzzEdit to re-scan the saved SFX library folders now."""
    result = BuzzEditClient().refresh_sfx_library()
    if result is None:
        raise HTTPException(status_code=502, detail="BuzzEdit did not answer (is it running?).")
    return result


class SfxGenerateSchema(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)
    kind: str = "accent"
    seconds: Optional[float] = None


@router.post("/api/produce/sfx/generate")
def generate_sfx_route(payload: SfxGenerateSchema):
    """Ask BuzzEdit's ComfyUI-backed pipeline to generate one new effect."""
    try:
        return BuzzEditClient().generate_sfx(payload.text, kind=payload.kind, seconds=payload.seconds)
    except BuzzEditUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/api/produce/sfx/jobs/{job_id}")
def get_sfx_job_route(job_id: str):
    """Follow a BuzzEdit SFX generation job."""
    client = BuzzEditClient()
    try:
        resp = client._get(f"/api/sfx/jobs/{job_id}", timeout=(5, 15))
    except BuzzEditUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"No SFX job {job_id!r}.")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"BuzzEdit returned HTTP {resp.status_code}.")
    return resp.json()


@router.get("/api/produce/sfx/file")
def get_sfx_file_route(path: str):
    """Stream one SFX library/generated audio file straight from BuzzEdit."""
    try:
        resp = BuzzEditClient().sfx_file(path)
    except Exception as exc:  # noqa: BLE001 - BuzzEdit offline, not a route bug
        raise HTTPException(status_code=502, detail=str(exc))
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"BuzzEdit returned HTTP {resp.status_code}.")
    content_type = resp.headers.get("content-type", "audio/mpeg")
    return StreamingResponse(resp.iter_content(chunk_size=65536), media_type=content_type)


@router.post("/api/produce/buzzedit/start")
def start_buzzedit():
    """Manually trigger BuzzEdit startup."""
    try:
        health = ensure_buzzedit_running(timeout=75.0)
        return {
            "status": "started",
            "online": True,
            "comfyui_online": bool(health.get("comfyui_connected")),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _free_gpu_for_render(project_id: str) -> None:
    """Clear every local LLM off the card so ComfyUI has it to itself: LM
    Studio's models, the llama.cpp server (buzzcode's engine on 8089), and
    Ollama's resident models. Opt out with the `produce_unload_llm: false`
    config key. Never fatal -- a slower render beats a failed one."""
    if str(config_manager.get("produce_unload_llm", True)).lower() in ("false", "0", "no"):
        return
    _set_status(project_id, message="Freeing the GPU for the render (unloading local LLMs)...")
    cfg = load_llm_config()
    for name, step in (("LM Studio", _unload_lm_studio), ("llama.cpp", _stop_llamacpp), ("Ollama", _unload_ollama)):
        try:
            step(project_id, cfg)
        except Exception as exc:  # noqa: BLE001 - one stuck server must not block the others or the render
            logger.warning("produce_video(%s): could not free %s (%s).", project_id, name, exc)


def _unload_lm_studio(project_id: str, cfg: Dict[str, Any]) -> None:
    from integrations.llm import find_lms_binary

    lms = find_lms_binary()
    if not lms:
        logger.warning("produce_video(%s): LM Studio CLI (lms) not found; any LM Studio model stays loaded "
                       "beside ComfyUI.", project_id)
        return
    proc = subprocess.run([lms, "unload", "--all"], capture_output=True, text=True, timeout=60,
                          creationflags=_NO_WINDOW)
    logger.info("produce_video(%s): lms unload --all -> %s", project_id, (proc.stdout or proc.stderr).strip()[:200])


def _find_buzzcode_binary() -> Optional[str]:
    import shutil

    found = shutil.which("buzzcode")
    if found:
        return found
    for candidate in (os.path.expanduser(r"~/.cargo/bin/buzzcode.exe"), os.path.expanduser("~/.cargo/bin/buzzcode")):
        if os.path.exists(candidate):
            return candidate
    return None


def _llamacpp_port(cfg: Dict[str, Any]) -> Optional[int]:
    """The local port llama.cpp is configured on, or None when it points at
    another machine (never stop a server this box does not own)."""
    from urllib.parse import urlparse

    parsed = urlparse(str(cfg.get("llamacpp_url") or "http://127.0.0.1:8089/v1"))
    if (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
        return None
    return parsed.port or 8089


def _stop_llamacpp(project_id: str, cfg: Dict[str, Any]) -> None:
    """A llama-server cannot drop its model without exiting, so stop it.

    `buzzcode engine stop` first: it kills the server tree before its
    supervisor (the other way round orphans llama-server with its VRAM) and
    withdraws the port-ledger entry. Anything still listening on the port
    afterwards is killed only if it is a llama-server -- never whatever else
    happens to hold it."""
    port = _llamacpp_port(cfg)
    if port is None:
        return
    buzzcode = _find_buzzcode_binary()
    if buzzcode:
        proc = subprocess.run([buzzcode, "engine", "stop"], capture_output=True, text=True, timeout=30,
                              creationflags=_NO_WINDOW)
        logger.info("produce_video(%s): buzzcode engine stop -> %s", project_id,
                    (proc.stdout or proc.stderr).strip()[:200])
    try:
        import psutil
    except ImportError:
        logger.warning("produce_video(%s): psutil missing; cannot check for a stray llama-server on :%d.",
                       project_id, port)
        return
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status != psutil.CONN_LISTEN or not conn.laddr or conn.laddr.port != port or not conn.pid:
            continue
        try:
            server = psutil.Process(conn.pid)
            if not server.name().lower().startswith("llama-server"):
                logger.info("produce_video(%s): :%d is held by %s, not a llama-server; leaving it alone.",
                            project_id, port, server.name())
                continue
            for child in server.children(recursive=True):
                child.kill()
            server.kill()
            server.wait(timeout=10)
            logger.info("produce_video(%s): stopped llama-server (pid %d) on :%d.", project_id, conn.pid, port)
        except psutil.Error as exc:
            logger.warning("produce_video(%s): could not stop llama-server pid %s (%s).", project_id, conn.pid, exc)


def _unload_ollama(project_id: str, cfg: Dict[str, Any]) -> None:
    """Evict every resident Ollama model (`keep_alive: 0`); the server stays up."""
    base = str(cfg.get("ollama_url") or "http://localhost:11434/v1").rstrip("/")
    base = base[:-3] if base.endswith("/v1") else base
    try:
        resident = requests.get(f"{base}/api/ps", timeout=2).json().get("models") or []
    except (requests.RequestException, ValueError):
        return  # Ollama is not running
    for model in resident:
        name = model.get("name") or model.get("model")
        if name:
            requests.post(f"{base}/api/generate", json={"model": name, "keep_alive": 0}, timeout=15)
            logger.info("produce_video(%s): unloaded Ollama model %s.", project_id, name)


def _produce_video_steps(
    project_id: str,
    recording_path: str,
    settings_override: Optional[Dict[str, Any]],
    mode: str,
    precut: bool = True,
) -> None:
    project = Project.load(project_id)
    client = BuzzEditClient()

    # 1. Sentinel -- advisory only. BuzzEdit runs its own ComfyUI/VRAM checks
    # once the render actually starts; this is purely a logged heads-up.
    try:
        from integrations.sentinel_client import client as sentinel_client

        granted, details = sentinel_client().query(mib=8192)  # ComfyUI ballpark, ECOSYSTEM.md
        if not granted:
            logger.warning("produce_video(%s): Sentinel flagged tight VRAM: %s", project_id, details)
    except Exception as exc:
        logger.debug("produce_video(%s): Sentinel query failed (%s); proceeding.", project_id, exc)

    # 2. BuzzEdit must be up, and ComfyUI must be online.
    # If BuzzEdit is not running, automatically start it and wait for it!
    def _status_cb(msg: str, progress: float):
        _set_status(project_id, state="running", message=msg, progress=progress)

    health = ensure_buzzedit_running(status_callback=_status_cb, timeout=75.0)
    if not health.get("comfyui_connected"):
        logger.warning("BuzzEdit online, but ComfyUI not marked connected; attempting to proceed.")

    # 3. Import the recording.
    _set_status(project_id, message="Importing the recording into BuzzEdit...", progress=0.05)
    imported = _with_buzzedit_retries(
        project_id, "import", lambda: client.import_recording(recording_path),
        status_cb=lambda msg: _set_status(project_id, message=msg))
    buzzedit_project_id = imported.get("id")
    if not buzzedit_project_id:
        raise RuntimeError(f"BuzzEdit did not return a project id for the imported recording: {imported}")
    project.metadata["buzzedit_project_id"] = buzzedit_project_id
    for stale in ("buzzedit_job_id", "output_path", "buzzedit_report", "produce_gate", "cut_check"):
        project.metadata.pop(stale, None)
    project.save()
    event_bus.publish("video_progress", {"project_id": project_id, "stage": "imported", "progress": 0.05})
    produce_queue.checkpoint(project_id, "transcribe")

    _transcribe_and_continue(project_id, settings_override, mode, precut)


def _speaker_style_text(brand: str) -> str:
    """About the speaker, for BuzzEdit's AI cut editor (BuzzEdit AUTO_CUT_V3_PLAN.md §2 item 6),
    from his writing style: the fixed opening line, his voice in one paragraph, his habitual
    phrases and the words he never uses. At most 1500 characters; "" when it cannot be read."""
    try:
        from app.services import writing_style
        lines = ["Fixed opening line (said once): " + writing_style.greeting(brand)]
        info = writing_style.overview(brand)
        voice: List[str] = []
        under = False
        for line in str(info.get("profile") or "").splitlines():
            if line.lstrip().startswith("#"):
                if under:
                    break
                under = line.strip().strip("#").strip().lower() == "his voice in one paragraph"
                continue
            if under and line.strip():
                voice.append(line.strip())
            elif under and voice:
                break
        if voice:
            lines.append(" ".join(voice)[:700])
        phrases = [str(p) for p in ((info.get("fingerprint") or {}).get("phrases") or [])[:15]]
        if phrases:
            lines.append("Habitual phrases: " + "; ".join(phrases))
        never = writing_style.never_words(writing_style.canonical_channel(brand))
        if never:
            lines.append("Never uses: " + ", ".join(str(w) for w in never))
        return "\n".join(lines)[:1500]
    except Exception:
        return ""


def _transcribe_and_continue(
    project_id: str,
    settings_override: Optional[Dict[str, Any]],
    mode: str,
    precut: bool,
    recut: bool = False,
) -> None:
    """Steps 4-5 against the already-imported BuzzEdit project, then on to
    planning (or the cuts-review gate). A queue item paused or failed right
    after import resumes here, without importing the recording again."""
    project = Project.load(project_id)
    client = BuzzEditClient()
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    if not buzzedit_project_id:
        raise RuntimeError("This project has no BuzzEdit project id to transcribe.")

    # 3b. Teleprompter eye-contact correction, when the project asks for it:
    # before anything reads the picture, so the cut, the face zooms and the
    # render all use the corrected recording. A failure does not stop the
    # video -- it is produced from the original, with a warning.
    if (project.metadata.get("eye_contact") or {}).get("enabled"):
        from app.api.eye_contact_api import correct_recording

        def _eye_progress(stage: str, fraction: float) -> None:
            _set_status(project_id, message=f"Fixing eye contact on BuzzEdit: {stage} ({int(fraction * 100)}%)",
                        progress=0.05 + 0.05 * fraction)

        try:
            correct_recording(project_id, client, buzzedit_project_id, _eye_progress)
        except Exception as exc:  # noqa: BLE001 - optional step
            logger.warning("produce_video(%s): eye contact correction failed (%s); using the original.",
                           project_id, exc)
            _set_status(project_id, warning=f"Eye contact was not fixed: {exc}")

    # 4. Read the script early (before transcribing) so its cleaned, spoken-only
    # text can seed BuzzEdit's transcription vocabulary -- proper nouns and
    # brand terms Whisper's own vocabulary would not otherwise favour.
    if mode == "script_first":
        script_text = _read_project_text_asset(project, ["script"]) or ""
    else:
        script_text = ""

    vocabulary = (extract_vocabulary(clean_spoken_script(script_text, _cast_speakers(project)))
                  if script_text else [])

    # 5. Transcribe (blocks on BuzzEdit's side until Whisper -- plus, unless
    # the recording is precut, the fumble/silence auto-edit -- finishes).
    _set_status(project_id, message=("Transcribing on BuzzEdit (keeping your cut)..." if precut
                                     else "Transcribing and auto-cutting on BuzzEdit..."), progress=0.15)
    # The channel's pacing (how long a pause may stay, how much room a cut
    # keeps) rides along; it only matters when BuzzEdit auto-cuts, i.e. not
    # for a precut recording. So does its genre: a channel with no pacing of
    # its own is paced by genre on BuzzEdit's side (horror keeps its pauses).
    channel_profile = get_channel_profile(project.brand)
    auto_edit = None if precut else clean_auto_edit(channel_profile.get("auto_edit"))
    # Whisper's language is pinned, never auto-detected: every channel here
    # is spoken in Hindi (Hinglish), and detection called a take Urdu and
    # wrote the whole transcript in Urdu script.
    language = str(channel_profile.get("language") or TRANSCRIBE_LANGUAGE).strip() or TRANSCRIBE_LANGUAGE
    # The AI cut editor on BuzzEdit's side needs the proxy key before it runs.
    sync_claude_key_to_buzzedit(client)

    def _transcribe_progress(stage: str) -> None:
        _set_status(project_id, message=f"BuzzEdit: {stage}...", progress=0.15)

    def _transcribe_once():
        # A transcription that finished after the Studio stopped waiting (or
        # before a retry) is already on the BuzzEdit project: use it.
        if client.is_transcribed(buzzedit_project_id):
            if recut and not precut:
                # The queue's "Re-cut": the words stay, the cut is planned
                # again under the current rules, no Whisper.
                logger.info("produce_video(%s): re-planning the cut on BuzzEdit project %s.",
                            project_id, buzzedit_project_id)
                _set_status(project_id, message="Re-cutting on BuzzEdit...", progress=0.15)
                return client.recut(buzzedit_project_id, progress_cb=_transcribe_progress)
            logger.info("produce_video(%s): BuzzEdit project %s is already transcribed; not transcribing again.",
                        project_id, buzzedit_project_id)
            return {"status": "completed", "reused": True}
        return client.transcribe(buzzedit_project_id, language=language, precut=precut,
                                 vocabulary=vocabulary or None, glossary=brand_key(project.brand),
                                 auto_edit=auto_edit, genre=channel_profile.get("genre"),
                                 speaker_style=_speaker_style_text(project.brand),
                                 progress_cb=_transcribe_progress)

    _with_buzzedit_retries(project_id, "transcription", _transcribe_once,
                           status_cb=lambda msg: _set_status(project_id, message=msg))
    event_bus.publish("video_progress", {"project_id": project_id, "stage": "transcribed", "progress": 0.25})

    review_mode = _resolve_review_mode(project)
    if review_mode == "cuts_and_plan":
        _save_gate(project, "cut_review", mode, settings_override, precut)
        _set_status(project_id, state="awaiting_cut_review", progress=0.28,
                    message="Auto-cut finished. Review the cut in BuzzEdit's Cuts view, then continue.")
        event_bus.publish("video_progress",
                           {"project_id": project_id, "stage": "awaiting_cut_review", "progress": 0.28})
        return

    # After the gate, not before it: a pause honoured here resumes straight
    # into planning, which would skip a cuts review the creator asked for.
    produce_queue.checkpoint(project_id, "plan")
    _plan_and_render(project_id, mode, settings_override, precut)


#: Script beats that are not pictures: still placed where the line is spoken.
SCRIPT_CUE_KINDS = frozenset({"music_cue", "sfx_cue"})


def _place_script_cues(rec: "Reconciliation", visual_plan: Dict[str, Any]) -> int:
    """The recording is the source of truth for visuals: the script's
    pre-recording pictures and clips are never placed, only offered to the
    take planner as ideas (`script_reference_section`). Its music and sound
    cues still land on the line they were written for, when that line is spoken."""
    placed = 0
    for beat in visual_plan.get("beats") or []:
        if isinstance(beat, dict) and beat.get("kind") in SCRIPT_CUE_KINDS:
            placed += bool(rec.place_script_beat(beat))
    return placed


def _plan_and_render(
    project_id: str,
    mode: str,
    settings_override: Optional[Dict[str, Any]],
    precut: bool,
) -> None:
    """Re-plan visuals against the CUT take and either render straight
    through or pause for a plan review. Shared by a fresh run that skipped
    the cuts-review gate and by `produce_video/continue` resuming past one --
    kept words are always fetched fresh here, since a cuts review may have
    just changed which ones survived.
    """
    project = Project.load(project_id)
    client = BuzzEditClient()
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    if not buzzedit_project_id:
        raise RuntimeError("This project has no BuzzEdit project id to plan visuals against.")

    if mode == "script_first":
        script_text = _read_project_text_asset(project, ["script"]) or ""
        visual_plan = _load_visual_plan(project)
    else:
        script_text, visual_plan = "", {"beats": []}

    # 6. Build the directive-annotated script from what was actually SAID --
    # and, now that the cut is final, from what SURVIVED the cut. The kept
    # words (not the full pre-cut transcript, which still has the removed
    # fumbles in it) are both the alignment target and the material the
    # visual-plan windows below are chunked from.
    _set_status(project_id, message="Matching your recording against the script...", progress=0.3)
    kept_words = client.get_kept_words(buzzedit_project_id)
    if not kept_words:
        raise RuntimeError("BuzzEdit returned no kept words to build the edit from.")

    prod_dir = os.path.join(project.get_project_dir(), "production")
    os.makedirs(prod_dir, exist_ok=True)

    # The cast's names make their upper-case `NAME:` lines dialogue, labelled
    # for BuzzEdit's voice conversion (`script_reconcile`).
    speakers = _cast_speakers(project)
    rec = Reconciliation(script_text, kept_words, speakers=speakers)
    _place_script_cues(rec, visual_plan)

    # 6b. Plan visuals for the take itself: windowed at ~60-90s (small enough
    # to answer well inside the local model's read timeout) and anchored by
    # word index (not a verbatim quote -- a small local model tends to
    # paraphrase one just enough to break exact matching). Script beats that
    # were spoken are already placed above; a window only needs a NEW beat
    # where coverage is still short, which is why each window's prompt is
    # told what already landed inside it (`rec.placed`).
    settings = settings_for_brand(project.brand, settings_override, project)
    genre = settings.get("genre", "general")
    genre_secondary = settings.get("genre_secondary")
    fx_palette = fx_palette_for(project.brand, genre, genre_secondary)
    bpm_target = beats_per_minute_target(settings)

    windows = chunk_kept_words(kept_words)
    planning: Dict[str, Any] = {"beats": [], "windows": 0, "ok": 0, "failed": []}
    if windows:
        from core.agent import AgentFactory

        # One agent per worker thread: a BaseAgent's LLMService keeps per-call
        # state (`last_response_simulated`) that parallel windows would race on.
        def _agent():
            return AgentFactory.get_agent("PromptEngineer", produce_llm_service())

        agent = _agent()
        workers = workers_for(agent)
        configured_workers = load_llm_config().get("produce_plan_workers")
        if configured_workers:
            try:
                workers = max(1, int(configured_workers))
            except (TypeError, ValueError):
                pass
        via = " via Claude" if produce_llm_provider() == "claude" else ""
        logger.info("produce_video(%s): planning %d window(s) with %d worker(s)%s.",
                    project_id, len(windows), workers, via)

        def _planning_progress(n: int, total: int) -> None:
            _set_status(project_id, message=f"Planning visuals for your take ({n + 1}/{total}{via})...",
                        progress=0.3 + 0.05 * (n + 1) / total)

        if produce_llm_provider() != "claude":
            # A local model plans next; BuzzEdit's transcription just left
            # Whisper + the aligner (~4 GB) on the card, which starved two
            # parallel windows into "failed to decode" on a 16 GB GPU.
            try:
                freed = client.clear_vram()
                logger.info("produce_video(%s): BuzzEdit freed the GPU before planning (comfyui_freed=%s).",
                            project_id, freed.get("comfyui_freed"))
            except Exception as exc:  # noqa: BLE001 - planning still runs, just tighter
                logger.warning("produce_video(%s): could not ask BuzzEdit to free the GPU (%s).", project_id, exc)
        try:
            from integrations.music_catalog import planner_direction
            music_direction = planner_direction(project)
        except Exception as exc:  # noqa: BLE001 - planning runs without it
            logger.warning("produce_video(%s): no music direction for planning (%s).", project_id, exc)
            music_direction = ""
        # A story channel plans pictures and clips only, against a cast sheet
        # so the same characters appear in every shot (story_visuals.py).
        catalog_section = None
        if is_story_style(settings):
            _set_status(project_id, message="Writing the cast sheet so characters stay the same...")
            story_text = script_text or " ".join(
                str(w.get("word") or w.get("text") or "") for w in kept_words)
            cast = story_visuals.ensure_cast_sheet(
                project, story_text,
                lambda: AgentFactory.get_agent("CharacterPlanner", produce_llm_service()))
            # A cast sheet written just now can name characters whose `NAME:`
            # lines the match above took for production notes: match again.
            names = story_visuals.character_names(cast)
            if script_text and names != speakers and script_speakers(script_text, names) != rec.speakers:
                rec = Reconciliation(script_text, kept_words, speakers=names)
                _place_script_cues(rec, visual_plan)
            catalog_section = story_visuals.planner_section(
                float(settings.get("video_broll_share") or 0.0), cast)
        planning = plan_visual_windows(agent, windows, kept_words, rec.placed, genre, genre_secondary,
                                       fx_palette, bpm_target, progress_cb=_planning_progress,
                                       workers=workers, agent_factory=_agent,
                                       music_direction=music_direction,
                                       catalog_section=catalog_section,
                                       reference_section=script_reference_section(visual_plan))
        if catalog_section:
            planning["beats"] = story_visuals.filter_beats(planning["beats"])

        # 6c. A dedicated SoundDesigner pass cues the scene's own sounds --
        # footsteps, a scream, a door, rain -- on top of whatever the window
        # planner above already cued alongside its pictures. Best-effort: a
        # failed pass just leaves the plan as it was, never fails production.
        if settings.get("sfx_diegetic", True):
            try:
                _set_status(project_id, message="Cueing the scene's sounds...")
                sound_agent = AgentFactory.get_agent("SoundDesigner", produce_llm_service())

                def _sound_progress(n: int, total: int) -> None:
                    _set_status(project_id, message=f"Cueing the scene's sounds ({n + 1}/{total})...")

                cues = sound_cues.plan_sound_cues(sound_agent, windows, kept_words, planning["beats"],
                                                  genre, genre_secondary, progress_cb=_sound_progress)
                planning["beats"] = cues["beats"]
                planning["sound_cues"] = {k: cues[k] for k in ("added", "spans", "ok", "failed")}
            except Exception as exc:  # noqa: BLE001 - sound cues never fail a production
                logger.warning("produce_video(%s): sound-cue pass failed (%s); plan unchanged.",
                               project_id, exc)

    all_failed = planning["windows"] > 0 and planning["ok"] == 0
    warning = None
    if planning["failed"]:
        warning = f"{len(planning['failed'])} of {planning['windows']} visual-planning window(s) failed and were skipped."
    if all_failed:
        warning = (warning + " " if warning else "") + "Every planning window failed; review before rendering."
    _set_status(project_id, planning=planning, warning=warning)

    stored_beats = [dict(beat, deleted=False) for beat in planning["beats"]]
    plan_path = os.path.join(prod_dir, "visual_plan_take.json")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump({"beats": stored_beats, "planning": planning}, f, indent=2, ensure_ascii=False)
    project.assets["visual_plan_take"] = "production/visual_plan_take.json"
    if mode != "script_first":
        project.assets["visual_plan"] = "production/visual_plan_take.json"
    project.save()

    # A plan review pauses here for the creator's edits. So does a straight
    # run where every window failed -- a bare video with zero new visuals for
    # an un-scripted take is worse than one extra click.
    review_mode = _resolve_review_mode(project)
    if review_mode in ("plan", "cuts_and_plan") or all_failed:
        _save_gate(project, "plan_review", mode, settings_override, precut)
        message = ("Every visual-planning window failed -- review before rendering."
                   if all_failed else "Visual plan ready for review.")
        _set_status(project_id, state="awaiting_plan_review", message=message, progress=0.35)
        event_bus.publish("video_progress",
                           {"project_id": project_id, "stage": "awaiting_plan_review", "progress": 0.35})
        return

    produce_queue.checkpoint(project_id, "finalize")
    for beat in stored_beats:
        rec.place_transcript_beat(beat)
    _finalize_and_render(project_id, mode, settings_override, precut, rec)


def _continue_after_cut_review(
    project_id: str,
    mode: str,
    settings_override: Optional[Dict[str, Any]],
    precut: bool,
) -> None:
    """Resume a run paused at `awaiting_cut_review`."""
    _clear_gate(Project.load(project_id))
    _set_status(project_id, message="Resuming after cut review...", progress=0.29)
    _plan_and_render(project_id, mode, settings_override, precut)


def _continue_after_plan_review(
    project_id: str,
    mode: str,
    settings_override: Optional[Dict[str, Any]],
    precut: bool,
    edited_plan: Optional[List[Dict[str, Any]]],
) -> None:
    """Resume a run paused at `awaiting_plan_review`: place the (possibly
    creator-edited) beats and render. The Reconciliation is rebuilt fresh from
    kept words and the script beats rather than carried across the pause, so
    this is safe to call from a brand new process after a restart."""
    project = Project.load(project_id)
    client = BuzzEditClient()
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    if not buzzedit_project_id:
        raise RuntimeError("This project has no BuzzEdit project id to render against.")

    if mode == "script_first":
        script_text = _read_project_text_asset(project, ["script"]) or ""
        # `visual_plan` now points at visual_plan_take.json for record_first
        # projects (see `_plan_and_render`), so only a script-first run reads
        # it here -- otherwise the take's own beats would be placed twice.
        visual_plan = _load_visual_plan(project)
    else:
        script_text, visual_plan = "", {"beats": []}

    _set_status(project_id, message="Resuming after plan review...", progress=0.32)
    kept_words = client.get_kept_words(buzzedit_project_id)
    if not kept_words:
        raise RuntimeError("BuzzEdit returned no kept words to build the edit from.")

    rec = Reconciliation(script_text, kept_words, speakers=_cast_speakers(project))
    _place_script_cues(rec, visual_plan)

    if edited_plan is not None:
        plan_beats: List[Dict[str, Any]] = edited_plan
    else:
        plan_path = os.path.join(project.get_project_dir(), "production", "visual_plan_take.json")
        plan_beats = []
        if os.path.exists(plan_path):
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_beats = (json.load(f) or {}).get("beats") or []

    for beat in plan_beats:
        if not isinstance(beat, dict) or beat.get("deleted"):
            continue
        prompt = beat.get("prompt")
        if prompt:
            beat = apply_prompt_edit(beat, prompt)
        rec.place_transcript_beat(beat)

    _finalize_and_render(project_id, mode, settings_override, precut, rec)


def _effects_review_wanted(project: Project) -> bool:
    return bool((project.metadata.get("video_settings") or {}).get("effects_review"))


def effects_sample_url(buzzedit_project_id: Optional[str]) -> Optional[str]:
    base = buzzedit_base_url()
    if not base or not buzzedit_project_id:
        return None
    return f"{base}/api/presentation/{buzzedit_project_id}/effects_sample/video"


def _render_settings(project: Project, settings_override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The settings BuzzEdit renders this project with (and samples with)."""
    settings = settings_for_brand(project.brand, settings_override, project)
    llm_fields = buzzedit_llm_settings()
    return {**settings, **llm_fields} if llm_fields else settings


def run_effects_sample(project_id: str, settings_override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ask BuzzEdit for the effects sample and wait for it. Returns
    {url, result, rendered_at}; raises if BuzzEdit fails or times out."""
    project = Project.load(project_id)
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    if not buzzedit_project_id:
        raise RuntimeError("This project has no BuzzEdit project to sample.")
    client = BuzzEditClient()
    _free_gpu_for_render(project_id)
    client.start_effects_sample(buzzedit_project_id, _render_settings(project, settings_override))
    deadline = time.monotonic() + _EFFECTS_SAMPLE_TIMEOUT_SECONDS
    while True:
        status = client.get_effects_sample(buzzedit_project_id)
        state = status.get("status")
        if state == "completed":
            break
        if state == "failed":
            raise RuntimeError(status.get("error") or status.get("message") or "The effects sample failed.")
        if time.monotonic() > deadline:
            raise RuntimeError("BuzzEdit took too long to render the effects sample.")
        _set_status(project_id, message=status.get("message") or "Rendering the effects sample...",
                    sample_progress=status.get("progress"))
        time.sleep(2.0)
    sample = {"url": effects_sample_url(buzzedit_project_id), "result": status.get("result") or {},
              "rendered_at": time.time()}
    project = Project.load(project_id)
    project.metadata["effects_sample"] = sample
    project.save()
    return sample


def _finalize_and_render(
    project_id: str,
    mode: str,
    settings_override: Optional[Dict[str, Any]],
    precut: bool,
    rec: Reconciliation,
) -> None:
    """Render the annotated script, hand it to BuzzEdit, and enqueue the
    render. The tail shared by a straight-through run and by
    `produce_video/continue` resuming past a plan review.

    With `video_settings.effects_review` on, the first arrival here renders
    an effects sample and parks at the `effects_review` gate instead;
    continuing that gate marks this BuzzEdit project approved and comes
    back through here to render for real."""
    project = Project.load(project_id)
    client = BuzzEditClient()
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    if _effects_review_wanted(project) and project.metadata.get("effects_approved_for") != buzzedit_project_id:
        _set_status(project_id, message="Rendering a 20-second effects sample for review...", progress=0.36)
        sample = run_effects_sample(project_id, settings_override)
        _save_gate(Project.load(project_id), "effects_review", mode, settings_override, precut)
        _set_status(project_id, state="awaiting_effects_review", progress=0.38, effects_sample=sample,
                    stage="effects_review",
                    message="Effects sample ready. Watch it, re-test after changing settings, then continue.")
        event_bus.publish("video_progress",
                          {"project_id": project_id, "stage": "awaiting_effects_review", "progress": 0.38})
        return

    # Each story character's lines carry their label, which BuzzEdit reads to
    # convert them to the character's voice (`apply_voice_map_to_buzzedit`).
    annotated_text = rec.render(speaker_labels=True)
    # What he actually said, and how he rephrased the script while saying it,
    # is the best evidence of his own style: kept for the writing agents.
    from app.services import writing_style
    writing_style.harvest_from_reconciliation(project, rec)
    render_settings = settings_for_brand(project.brand, settings_override, project)
    if is_story_style(render_settings):
        # Pictures and clips only, the cast's looks on every shot, and the
        # clip share enforced here -- BuzzEdit renders every directive it is
        # handed and never turns a script's still into a clip. The share is
        # of the video's running time: every shot is timed from the edited
        # programme's word times and carries its own length.
        annotated_text, story_stats = story_visuals.apply_to_script(
            annotated_text, float(render_settings.get("video_broll_share") or 0.0),
            story_visuals.load_cast_sheet(project),
            word_times=rec.word_times, duration_s=rec.duration_s,
            clip_max_s=float(render_settings.get("broll_seconds_max") or story_visuals.CLIP_MAX_SECONDS),
            image_share=float(render_settings.get("image_broll_share") or 0.0))
        logger.info("produce_video(%s): story visuals -- %s.", project_id, story_stats)
        _set_status(project_id, story_visuals=story_stats)
    deviation = rec.report()
    prod_dir = os.path.join(project.get_project_dir(), "production")
    os.makedirs(prod_dir, exist_ok=True)
    with open(os.path.join(prod_dir, "script_deviation.json"), "w", encoding="utf-8") as f:
        json.dump(deviation, f, indent=2, ensure_ascii=False)
    project.assets["script_deviation"] = "production/script_deviation.json"
    summary = {k: deviation[k] for k in ("script_spoken_share", "adlib_share", "beats_placed")}
    summary["beats_dropped"] = len(deviation["beats_dropped"])
    summary["skipped_paragraphs"] = len(deviation["skipped_paragraphs"])
    project.metadata["script_deviation"] = summary
    project.metadata["precut"] = precut
    if deviation["beats_dropped"]:
        logger.info("produce_video(%s): %d planned visual(s) dropped (lines not spoken or unplaceable).",
                    project_id, len(deviation["beats_dropped"]))
    _set_status(project_id, deviation=summary)

    script_dir = os.path.join(project.get_project_dir(), "script")
    os.makedirs(script_dir, exist_ok=True)
    annotated_path = os.path.join(script_dir, "buzzedit_script.md")
    with open(annotated_path, "w", encoding="utf-8") as f:
        f.write(annotated_text)
    project.assets["buzzedit_script"] = "script/buzzedit_script.md"
    project.metadata.pop("produce_gate", None)
    project.save()

    # 7. Push the annotated script onto the BuzzEdit project (aligns to the
    # transcript now that step 5 has run).
    _set_status(project_id, message="Sending the annotated script to BuzzEdit...", progress=0.35)
    client.set_script(buzzedit_project_id, annotated_text)

    # 8. Enqueue the presentation-pass render -- after handing the GPU over:
    # the visual planning just loaded a local LLM, and ComfyUI beside it on a
    # 16 GB card crawls (ECOSYSTEM.md: at most one heavy GPU tenant).
    _free_gpu_for_render(project_id)
    settings = settings_for_brand(project.brand, settings_override, project)
    # Tell BuzzEdit which model to run its own passes (moods, topics, picture
    # prompts) on, and make sure it holds the Pixabay key before a render
    # that may fall back to stock footage.
    llm_fields = buzzedit_llm_settings()
    if llm_fields:
        settings = {**settings, **llm_fields}
    if is_story_style(settings):
        # The face BuzzEdit swaps into every `face=main` shot ({} = the story
        # has no lead: swap nothing, guess nothing). Read once per render, so a
        # hand-edited cast sheet takes effect on the next one.
        main_face = story_visuals.buzzedit_main_character(story_visuals.load_cast_sheet(project))
        if main_face is not None:
            settings = {**settings, "main_character": main_face}
    if settings.get("allow_free_stock"):
        sync_stock_keys_to_buzzedit(client)
    sync_thinking_to_buzzedit(client)
    sync_claude_key_to_buzzedit(client)
    sync_clip_generation_to_buzzedit(client)
    sync_sfx_library_to_buzzedit(client)
    # The channel's audio rack preset onto the edit's A1 rack (the voice).
    apply_audio_rack_to_buzzedit(project, client, buzzedit_project_id)
    # The story's character lines in their cast voices, before the mix; the
    # creator's narration stays his own.
    apply_voice_map_to_buzzedit(project, client, buzzedit_project_id)
    # The live file mirrors this pass's own mix from the start, so a change
    # made during an earlier pass never leaks into this one unasked.
    push_live_settings(project, client, settings=settings)
    planner = " Â· planning with Claude" if llm_fields else ""
    _set_status(project_id, message=f"Enqueuing the render (genre={settings.get('genre')}{planner})...", progress=0.4)
    enqueue_resp = client.enqueue_presentation(buzzedit_project_id, settings, start_at="")
    job = enqueue_resp.get("job") or {}
    job_id = job.get("id")
    if not job_id:
        raise RuntimeError(f"BuzzEdit did not return a job id for the enqueued render: {enqueue_resp}")
    event_bus.publish("video_progress", {"project_id": project_id, "stage": "enqueued", "progress": 0.4, "buzzedit_job_id": job_id})
    project = Project.load(project_id)
    project.metadata["buzzedit_job_id"] = job_id
    project.save()
    produce_queue.checkpoint(project_id, "render")

    _await_render(project_id, client, buzzedit_project_id, job_id)


#: How far below the asked-for clip share a render may land before the
#: creator is told (rounding of shot lengths to word boundaries).
RUNTIME_MIX_TOLERANCE = 0.03


def _check_runtime_mix(project: Project, client: BuzzEditClient, buzzedit_project_id: str,
                       report: Optional[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Measure the finished edit's clip / picture shares against the mix the
    creator set ("70% video" = 70% of the final video is generated clips),
    and word a warning when the clips fall short."""
    try:
        from integrations.buzzedit_settings import achieved_mix, resolve_settings, runtime_mix
        achieved = achieved_mix(client.get_project(buzzedit_project_id))
        target = runtime_mix(resolve_settings(project.brand, None, project)[0])
    except Exception as exc:  # noqa: BLE001 - a report nicety; never fails the render
        logger.warning("produce_video(%s): could not measure the video share (%s).", project.id, exc)
        return None, None
    if not achieved:
        return None, None
    mix = {"target": {"video": target["video"], "images": target["images"]}, **achieved}
    logger.info("produce_video(%s): video %.1f%% (target %.0f%%), pictures %.1f%% (target %.0f%%), %d clips, %d stills.",
                project.id, 100 * achieved["video"], 100 * target["video"], 100 * achieved["images"],
                100 * target["images"], achieved["clips"], achieved["stills"])
    if achieved["video"] + RUNTIME_MIX_TOLERANCE >= target["video"]:
        return mix, None
    phase = (((report or {}).get("generation") or {}).get("video_phase") or {})
    why = phase.get("skipped_reason") or "fewer clips were placed than planned"
    return mix, (f"Video clips are {100 * achieved['video']:.0f}% of the video, not the {100 * target['video']:.0f}% "
                 f"you set ({phase.get('made', achieved['clips'])} of {phase.get('planned', '?')} clips made): {why}.")


def _await_render(project_id: str, client: BuzzEditClient, buzzedit_project_id: str, job_id: str) -> None:
    """Poll BuzzEdit's scheduler until `job_id` finishes, then record where
    the video landed. Shared by a fresh run and by `produce_video/resume`."""
    # 8. Poll BuzzEdit's scheduler until the job finishes or fails.
    deadline = time.monotonic() + _MAX_RENDER_SECONDS
    last_event_at = 0.0
    started_at = time.monotonic()
    unreachable_since: Optional[float] = None
    last_seen: Optional[tuple] = None
    last_change_at = time.monotonic()
    missing_since: Optional[float] = None
    while True:
        if produce_queue.cancel_requested(project_id):
            # BuzzEdit cannot abort a job mid-render; this drops a still-pending
            # one from its queue and stops tracking a running one.
            try:
                client.cancel_job(job_id)
            except Exception as exc:  # noqa: BLE001 - cancelling must not fail on a busy BuzzEdit
                logger.info("produce_video(%s): could not cancel BuzzEdit job %s (%s).", project_id, job_id, exc)
            raise produce_queue.ProduceCancelled()
        now_mono = time.monotonic()
        if now_mono > deadline:
            raise RuntimeError(f"Timed out waiting for BuzzEdit render job {job_id} after {_MAX_RENDER_SECONDS}s.")
        if now_mono - last_change_at > _RENDER_STALL_SECONDS:
            raise RuntimeError(
                f"BuzzEdit render job {job_id} made no progress for {_RENDER_STALL_SECONDS // 60} minutes; "
                "it looks stuck. Check BuzzEdit, then use Resume render.")
        try:
            jobs_resp = client.get_jobs()
            unreachable_since = None
        except (BuzzEditUnavailable, requests.RequestException) as exc:
            now = time.monotonic()
            unreachable_since = unreachable_since or now
            if now - unreachable_since > _MAX_UNREACHABLE_SECONDS:
                raise BuzzEditUnavailable(
                    f"BuzzEdit stopped answering for {_MAX_UNREACHABLE_SECONDS // 60} minutes "
                    f"during render job {job_id}: {exc}") from exc
            logger.info("produce_video(%s): BuzzEdit busy/unreachable (%s); still waiting.", project_id, exc)
            _set_status(project_id, message="BuzzEdit is busy on the GPU; still waiting for the render...")
            time.sleep(_POLL_INTERVAL_SECONDS * 2)
            continue
        matching = next((j for j in (jobs_resp.get("jobs") or []) if j.get("id") == job_id), None)
        if matching is None:
            # BuzzEdit keeps every job until someone clears finished ones, so
            # a job it does not list is one it never had or lost (a restart
            # before it saved, or a second BuzzEdit that took the enqueue and
            # died). Waiting the full stall timeout on it cost an hour.
            missing_since = missing_since or time.monotonic()
            if time.monotonic() - missing_since > _JOB_MISSING_SECONDS:
                raise RuntimeError(
                    f"BuzzEdit at {buzzedit_base_url()} has no render job {job_id}: it was lost "
                    "(BuzzEdit restarted, or another BuzzEdit took the job). Retry the production.")
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
        missing_since = None
        status = matching.get("status")
        job_progress = matching.get("progress")
        seen = (status, job_progress, matching.get("message"))
        if seen != last_seen:
            last_seen, last_change_at = seen, time.monotonic()
        overall_progress = 0.4 + 0.55 * float(job_progress or 0.0)
        _set_status(
            project_id,
            message=matching.get("message") or f"Rendering ({status})...",
            progress=min(overall_progress, 0.95),
            buzzedit_job_id=job_id,
        )
        elapsed = time.monotonic() - started_at
        if elapsed - last_event_at >= _PROGRESS_EVENT_EVERY_SECONDS:
            last_event_at = elapsed
            event_bus.publish("video_progress", {
                "project_id": project_id, "stage": "rendering", "progress": min(overall_progress, 0.95),
                "buzzedit_job_id": job_id, "buzzedit_status": status,
            })
        if status == "completed":
            break
        if status == "failed":
            raise RuntimeError(f"BuzzEdit render job {job_id} failed: {matching.get('error') or 'no error detail given'}")
        time.sleep(_POLL_INTERVAL_SECONDS)

    # 9. Fetch the report and record where the finished video landed.
    _set_status(project_id, message="Fetching the render report...", progress=0.97)
    report = client.get_report(buzzedit_project_id)
    output_path = None
    if report:
        output_path = report.get("output_path")
    if not output_path:
        buzzedit_project = client.get_project(buzzedit_project_id)
        output_path = (buzzedit_project or {}).get("output_path")

    project = Project.load(project_id)  # reload: the annotator step already saved once
    project.metadata["buzzedit_report"] = report
    # What the creator checks a cut for (BuzzEdit AUTO_CUT_V3_PLAN.md §2 item 10): the exact
    # repeats and false starts BuzzEdit's AI editor still counts in what plays.
    editor_report = (report or {}).get("editor")
    if isinstance(editor_report, dict):
        cut_check = {key: editor_report[key] for key in ("repeats_remaining", "false_starts_remaining")
                     if key in editor_report}
        if cut_check:
            project.metadata["cut_check"] = cut_check
    project.metadata["output_path"] = output_path
    mix, mix_warning = _check_runtime_mix(project, client, buzzedit_project_id, report)
    if mix:
        project.metadata["runtime_mix_achieved"] = mix
    project.save()

    _set_status(project_id, state="ready", message="Video ready.", progress=1.0, report=report, output_path=output_path,
                **({"warning": mix_warning} if mix_warning else {}))
    event_bus.publish("video_ready", {
        "project_id": project_id, "output_path": output_path,
        "report_summary": {
            "genre": (report or {}).get("genre"),
            "assets_generated": (report or {}).get("assets_generated"),
            "script_directives": (report or {}).get("script_directives"),
        } if report else None,
    })


def _find_render_job(project: Project, client: BuzzEditClient) -> Optional[Dict[str, Any]]:
    """This project's BuzzEdit render job (the stored id, or -- for runs from
    before it was stored -- the newest one BuzzEdit has for the project), or
    None if BuzzEdit has none. Raises BuzzEditUnavailable."""
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    job_id = project.metadata.get("buzzedit_job_id")
    jobs = client.get_jobs().get("jobs") or []
    if job_id:
        return next((j for j in jobs if j.get("id") == job_id), {"id": job_id})
    mine = [j for j in jobs if j.get("project_id") == buzzedit_project_id]
    if not mine:
        return None
    return sorted(mine, key=lambda j: str(j.get("created_at") or ""))[-1]


def _rerender_possible(client: BuzzEditClient, buzzedit_project_id: str, job: Dict[str, Any]) -> bool:
    """True when the failed `job` saved its finished timeline before dying, so
    only the render has to run again. BuzzEdit stamps `presented_at` when the
    pass saves the timeline; one stamped after the job started is that job's."""
    try:
        data = client.get_project(buzzedit_project_id) or {}
    except Exception as exc:  # noqa: BLE001 - fall back to the full pass
        logger.info("Could not read BuzzEdit project %s (%s); rendering from the plan.", buzzedit_project_id, exc)
        return False
    presented_at = str(data.get("presented_at") or "")
    started = str(job.get("started_at") or job.get("created_at") or "")
    return data.get("status") == "presented" and bool(presented_at) and bool(started) \
        and presented_at[:19] >= started[:19]


def _reattach_render(project_id: str, mode: str, settings_override: Optional[Dict[str, Any]],
                     precut: bool) -> None:
    """Pick a run back up at the render: follow BuzzEdit's job if it is still
    alive (or already done), or enqueue a fresh render from the saved plan if
    it failed, was cancelled, or is gone."""
    project = Project.load(project_id)
    client = BuzzEditClient()
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    if not buzzedit_project_id:
        raise RuntimeError("This project has no BuzzEdit render to resume.")
    job = _find_render_job(project, client)
    if job and job.get("status") in ("failed", "cancelled") and _rerender_possible(client, buzzedit_project_id, job):
        # The pass got as far as saving its timeline and only the ffmpeg render
        # died: render that again instead of re-running planning, pictures and music.
        _free_gpu_for_render(project_id)
        _set_status(project_id, message="The render did not finish; rendering the saved edit again...",
                    progress=0.4)
        job = (client.enqueue_rerender(buzzedit_project_id).get("job") or {})
        if not job.get("id"):
            raise RuntimeError("BuzzEdit did not return a job id for the re-render.")
        project = Project.load(project_id)
        project.metadata["buzzedit_job_id"] = job["id"]
        project.save()
        _await_render(project_id, client, buzzedit_project_id, job["id"])
        return
    if not job or job.get("status") in ("failed", "cancelled"):
        _set_status(project_id, message="The previous render did not finish; rendering again from the saved plan...",
                    progress=0.32)
        _continue_after_plan_review(project_id, mode, settings_override, precut, None)
        return
    job_id = job["id"]
    project.metadata["buzzedit_job_id"] = job_id
    project.save()
    if job.get("status") != "completed":
        # A model may have been loaded since the original hand-over.
        _free_gpu_for_render(project_id)
    _set_status(project_id, message="Re-attached to the BuzzEdit render...", progress=0.4, buzzedit_job_id=job_id)
    _await_render(project_id, client, buzzedit_project_id, job_id)


def run_queue_item(item: Dict[str, Any]) -> str:
    """Run one production-queue item from its `resume_from` point, on the
    queue's worker thread (`app/services/produce_queue.py`). Returns "done" or
    "awaiting_review"; raises on failure, or ProducePaused / ProduceCancelled
    at a checkpoint, after recording the outcome in `_produce_status`."""
    from app.main import active_executions

    project_id = item["project_id"]
    mode = item.get("mode") or "record_first"
    settings_override = item.get("settings_override")
    precut = bool(item.get("precut"))
    resume_from = item.get("resume_from") or "start"

    _set_status(project_id, state="running", message="Starting..." if resume_from == "start" else "Resuming...",
                error=None, warning=None, **({"planning": None, "progress": 0.0} if resume_from == "start" else {}))
    active_executions.add(project_id)
    try:
        if resume_from != "start":
            # Every later stage talks to BuzzEdit straight away. A resume right
            # after the Studio (and so BuzzEdit) restarted used to fail in
            # seconds with "not reachable" while BuzzEdit was still booting.
            ensure_buzzedit_running(
                status_callback=lambda msg, p: _set_status(project_id, message=msg, progress=p))
        if resume_from == "start":
            _produce_video_steps(project_id, item.get("recording_path") or "", settings_override, mode, precut)
        elif resume_from == "transcribe":
            recut = bool(item.get("recut"))
            if recut:
                produce_queue.consume_recut(item["id"])
            _transcribe_and_continue(project_id, settings_override, mode, precut, recut=recut)
        elif resume_from == "plan":
            _continue_after_cut_review(project_id, mode, settings_override, precut)
        elif resume_from == "finalize":
            _continue_after_plan_review(project_id, mode, settings_override, precut, None)
        elif resume_from == "render":
            _reattach_render(project_id, mode, settings_override, precut)
        else:
            raise RuntimeError(f"Unknown resume point '{resume_from}'.")
    except produce_queue.ProducePaused as paused:
        _set_status(project_id, state="paused", message=f"Paused. Resumes from the '{paused.resume_from}' stage.")
        event_bus.publish("video_progress", {"project_id": project_id, "stage": "paused"})
        raise
    except produce_queue.ProduceCancelled:
        _set_status(project_id, state="cancelled", message="Cancelled by user.")
        event_bus.publish("video_progress", {"project_id": project_id, "stage": "cancelled"})
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised for the queue
        if isinstance(exc, BuzzEditUnavailable):
            logger.warning("produce_video(%s): BuzzEdit unavailable: %s", project_id, exc)
        else:
            logger.exception("produce_video(%s) failed", project_id)
        _set_status(project_id, state="failed", error=str(exc))
        event_bus.publish("video_failed", {"project_id": project_id, "error": str(exc)})
        raise
    finally:
        active_executions.discard(project_id)

    state = _get_status(project_id).get("state") or ""
    return "awaiting_review" if state.startswith("awaiting") else "done"


def _queue_resume(project: Project, resume_from: str, gate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Put this project's parked/failed run back in line (ahead of new work),
    or queue a new item for a run that predates the queue."""
    item = produce_queue.active_item_for(project.id)
    if item is not None and item["status"] in ("queued", "running"):
        raise ValueError("This project is already in the production queue.")
    if item is None:
        # The newest finished item keeps its recording path and settings.
        finished = [i for i in produce_queue.snapshot()["items"] if i.get("project_id") == project.id]
        item = finished[-1] if finished else None
    if item is not None:
        return produce_queue.requeue(item["id"], resume_from, front=True)
    gate = gate or {}
    return produce_queue.add(
        project.id, brand=project.brand, title=project.name, recording_path="",
        settings_override=gate.get("settings_override"),
        mode=gate.get("mode") or ("script_first" if _has_script_first_assets(project) else "record_first"),
        precut=bool(gate.get("precut", project.metadata.get("precut", False))),
        resume_from=resume_from, front=True,
    )


@router.post("/api/projects/{project_id}/produce_video/resume")
def resume_produce_video(project_id: str):
    """Re-attach to this project's BuzzEdit render without re-importing or
    re-transcribing -- for when the Studio restarted, or lost BuzzEdit
    mid-render while the job itself kept going. Goes through the queue, so it
    waits its turn behind a video already on the GPU."""
    try:
        project = Project.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.metadata.get("buzzedit_project_id"):
        raise HTTPException(status_code=409, detail="This project has no BuzzEdit render to resume.")

    from app.main import active_executions

    if project_id in active_executions or _get_status(project_id).get("state") in ("starting", "running"):
        raise HTTPException(status_code=409, detail="This project already has work running.")

    try:
        item = _queue_resume(project, "render")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _set_status(project_id, state="queued", message="Waiting in the production queue to re-attach...", error=None)
    return {"status": "resumed", "project_id": project_id, "queue_item_id": item["id"]}


# ────────────────────────────── Review gates ──────────────────────────────


class ProduceVideoContinueSchema(BaseModel):
    stage: str  # "cut_review" | "plan_review" -- must match the pending gate
    # Edited beats for a "plan_review" continue: the whole beats list from
    # `production/visual_plan_take.json` (see GET .../produce_video/status'
    # `planning` block, and the file itself), each optionally with
    # `deleted: true` (dropped) or an edited `prompt` (folded back into the
    # field its `kind` renders from). Omitted -> the plan on disk is used
    # as-is. Ignored for a "cut_review" continue.
    plan: Optional[List[Dict[str, Any]]] = None


def _save_edited_plan(project: Project, beats: List[Dict[str, Any]]) -> None:
    """Write the creator's edited beats over `visual_plan_take.json`, so the
    queued continue (and any later retry) renders exactly what was reviewed."""
    plan_path = os.path.join(project.get_project_dir(), "production", "visual_plan_take.json")
    os.makedirs(os.path.dirname(plan_path), exist_ok=True)
    existing: Dict[str, Any] = {}
    if os.path.exists(plan_path):
        with open(plan_path, "r", encoding="utf-8") as f:
            existing = json.load(f) or {}
    existing["beats"] = beats
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


@router.post("/api/projects/{project_id}/produce_video/continue")
def continue_produce_video(project_id: str, payload: ProduceVideoContinueSchema):
    """Resume a run paused at a review gate (`awaiting_cut_review` or
    `awaiting_plan_review`). It goes back into the production queue ahead of
    new work -- behind a video already rendering -- and the gate is cleared
    now, since the queue item itself carries everything needed to resume,
    across a restart too."""
    project = _load_project_or_404(project_id)
    gate = project.metadata.get("produce_gate")
    if not gate or gate.get("stage") not in GATE_STAGES:
        raise HTTPException(status_code=409, detail="This project has no produce_video review gate pending.")
    stage = gate["stage"]
    if payload.stage != stage:
        raise HTTPException(status_code=409,
                             detail=f"This project is awaiting the '{stage}' gate, not '{payload.stage}'.")

    from app.main import active_executions

    if project_id in active_executions or _get_status(project_id).get("state") in ("starting", "running"):
        raise HTTPException(status_code=409, detail="This project already has work running.")

    if stage == "plan_review" and payload.plan is not None:
        _save_edited_plan(project, payload.plan)
    if stage == "effects_review":
        # The creator has seen the sample: the render that follows must not
        # stop for another one (`_finalize_and_render` checks this marker).
        project.metadata["effects_approved_for"] = project.metadata.get("buzzedit_project_id")
        project.save()

    _set_status(project_id, state="queued", message="Continuing -- waiting in the production queue...",
                error=None, warning=None)
    try:
        item = _queue_resume(project, _GATE_RESUME_POINT[stage], gate)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    project = Project.load(project_id)
    project.metadata.pop("produce_gate", None)
    project.save()
    return {"status": "resumed", "project_id": project_id, "stage": stage, "queue_item_id": item["id"]}


_sample_threads: Dict[str, threading.Thread] = {}


@router.post("/api/projects/{project_id}/produce_video/effects_sample")
def retest_effects_sample(project_id: str):
    """Render the effects sample again -- after a settings change -- while
    the run waits at the `effects_review` gate. Runs in the background; the
    status poll shows `sample_running` and then the new `effects_sample`."""
    project = _load_project_or_404(project_id)
    gate = project.metadata.get("produce_gate") or {}
    if gate.get("stage") != "effects_review":
        raise HTTPException(status_code=409, detail="This project is not waiting on an effects review.")
    running = _sample_threads.get(project_id)
    if running is not None and running.is_alive():
        raise HTTPException(status_code=409, detail="An effects sample is already rendering.")

    settings_override = gate.get("settings_override")
    _set_status(project_id, state="awaiting_effects_review", stage="effects_review", sample_running=True,
                sample_error=None, message="Re-rendering the effects sample with your current settings...")

    def run() -> None:
        try:
            sample = run_effects_sample(project_id, settings_override)
            _set_status(project_id, effects_sample=sample, sample_running=False,
                        message="New effects sample ready. Continue when it looks right.")
        except Exception as exc:  # noqa: BLE001 - surfaced on the status, the gate stays
            logger.warning("effects sample (%s) failed: %s", project_id, exc)
            _set_status(project_id, sample_running=False, sample_error=str(exc),
                        message=f"The effects sample failed: {exc}")

    thread = threading.Thread(target=run, name=f"effects-sample-{project_id}", daemon=True)
    _sample_threads[project_id] = thread
    thread.start()
    return {"status": "rendering", "project_id": project_id}


@router.post("/api/projects/{project_id}/produce_video/cancel")
def cancel_produce_video(project_id: str):
    """Cancel a run that is queued, paused, or sitting at a review gate. A run
    actively working is cancelled from the queue panel instead
    (`POST /api/produce/queue/{item_id}/cancel`), which stops it at its next
    checkpoint."""
    project = _load_project_or_404(project_id)
    if _get_status(project_id).get("state") in ("starting", "running"):
        raise HTTPException(status_code=409, detail="This project's render is already under way; it cannot be cancelled here.")

    had_gate = project.metadata.get("produce_gate") is not None
    project.metadata.pop("produce_gate", None)
    project.save()

    item = produce_queue.active_item_for(project_id)
    if item and item["status"] != "running":
        produce_queue.cancel(item["id"])

    from app.main import active_executions
    active_executions.discard(project_id)
    _set_status(project_id, state="cancelled", message="Cancelled by user.", error=None, warning=None)
    return {"status": "cancelled", "project_id": project_id, "had_pending_gate": had_gate}


# ────────────────────────────── Production queue ──────────────────────────────


def _queue_view() -> Dict[str, Any]:
    """The queue plus each item's live message/progress from `_produce_status`."""
    snap = produce_queue.snapshot()
    for item in snap["items"]:
        live = _get_status(item["project_id"])
        if item["status"] in ("running", "awaiting_review"):
            item["message"] = live.get("message")
            item["progress"] = live.get("progress")
            item["stage_state"] = live.get("state")
        elif item["status"] == "done":
            item["progress"] = 1.0
        else:
            # The same words `produce_video/status` uses, so both panels agree.
            item["message"] = _queue_message(item)
    return snap


@router.get("/api/produce/queue")
def get_produce_queue():
    return _queue_view()


class QueueAddSchema(ProduceVideoSchema):
    project_id: str


@router.post("/api/produce/queue")
def add_to_produce_queue(payload: QueueAddSchema):
    """Queue a video for production -- any project, any channel. Same checks
    and defaults as `POST /api/projects/{id}/produce_video`."""
    body = ProduceVideoSchema(**payload.model_dump(exclude={"project_id"}))
    return produce_video(payload.project_id, body)


class QueueBatchItem(BaseModel):
    # An existing project, or a new one made from `recording_path` + `title`.
    project_id: Optional[str] = None
    recording_path: Optional[str] = None
    title: Optional[str] = None


class QueueBatchSchema(BaseModel):
    brand: str
    # The channel's workflow for new projects (the UI knows the mapping:
    # frontend/src/lib/channels.ts `workflowFor`).
    workflow_name: Optional[str] = None
    items: List[QueueBatchItem]


def _title_from_recording(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return " ".join(stem.replace("_", " ").replace("-", " ").split()) or "Untitled video"


@router.post("/api/produce/queue/batch")
def add_batch_to_produce_queue(payload: QueueBatchSchema):
    """Queue several videos of one channel in one go, in the order given.

    Each item is an existing project of that channel (its recording taken
    from the item, else the one it was last produced from) or a new
    recording, which becomes a new project titled after the file. Items are
    independent: one that cannot be queued is reported and the rest still go."""
    from app.main import engine
    from executive.project import project_manager

    results: List[Dict[str, Any]] = []
    for entry in payload.items:
        result: Dict[str, Any] = {"project_id": entry.project_id, "recording_path": entry.recording_path}
        try:
            if entry.project_id:
                project = Project.load(entry.project_id)
                if project.brand != payload.brand:
                    raise ValueError(f"'{project.name}' belongs to {project.brand}, not {payload.brand}.")
                recording = (entry.recording_path or project.metadata.get("recording_path") or "").strip()
            else:
                recording = (entry.recording_path or "").strip()
                if not recording:
                    raise ValueError("A new video needs a recording.")
                if not os.path.exists(recording):
                    raise ValueError(f"Recording not found: {recording}")
                workflow = payload.workflow_name or ""
                if not engine.get_workflow(workflow):
                    raise ValueError(f"Workflow '{workflow}' not found for {payload.brand}.")
                base = (entry.title or "").strip() or _title_from_recording(recording)
                name, n = base, 1
                # Project ids are date + channel + title: a same-day twin gets "Part 2".
                while os.path.exists(os.path.join(project_manager.projects_dir,
                                                  project_manager.generate_project_id(payload.brand, name))):
                    n += 1
                    name = f"{base} Part {n}"
                project = project_manager.create_project(name=name, brand=payload.brand, workflow_name=workflow)
                result["created"] = True
                event_bus.publish("project_created", {
                    "project_id": project.id, "name": project.name, "brand": project.brand,
                    "workflow_name": project.workflow_name, "current_step": project.current_step,
                })
            result["project_id"] = project.id
            result["title"] = project.name
            if not recording:
                raise ValueError(f"'{project.name}' has no recording yet.")
            if not os.path.exists(recording):
                raise ValueError(f"Recording not found: {recording}")
            queued = produce_video(project.id, ProduceVideoSchema(recording_path=recording))
            result.update(status="queued", queue_item_id=queued["queue_item_id"])
        except HTTPException as exc:
            result.update(status="error", error=str(exc.detail))
        except (ValueError, FileNotFoundError) as exc:
            result.update(status="error", error=str(exc) or "Project not found")
        results.append(result)
    return {"results": results, "queued": sum(r["status"] == "queued" for r in results), **_queue_view()}


class QueuePausedSchema(BaseModel):
    paused: bool


@router.post("/api/produce/queue/paused")
def set_produce_queue_paused(payload: QueuePausedSchema):
    """Pause the whole queue: the video in progress carries on, nothing new
    starts until it is resumed."""
    produce_queue.set_paused(payload.paused)
    return _queue_view()


@router.post("/api/produce/queue/clear_finished")
def clear_finished_produce_queue():
    removed = produce_queue.clear_finished()
    return {"removed": removed, **_queue_view()}


class QueueActionSchema(BaseModel):
    direction: Optional[str] = None  # "up" | "down", for `move`


_QUEUE_ACTIONS = ("pause", "resume", "cancel", "retry", "restart", "recut", "move", "remove")


@router.post("/api/produce/queue/{item_id}/{action}")
def act_on_produce_queue_item(item_id: str, action: str, payload: Optional[QueueActionSchema] = None):
    if action not in _QUEUE_ACTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown queue action '{action}'.")
    try:
        item = produce_queue.get(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Queue item not found")
    previous_status = _get_status(item["project_id"])
    if action in ("retry", "restart", "recut", "resume") and item["status"] != "running":
        # Before the call, not after: the worker may pick the item up at once.
        _set_status(item["project_id"], state="queued", message="Waiting in the production queue...", error=None)
    try:
        if action == "pause":
            produce_queue.pause(item_id)
        elif action == "resume":
            produce_queue.resume(item_id)
        elif action == "cancel":
            if item["status"] == "awaiting_review":
                project = Project.load(item["project_id"])
                project.metadata.pop("produce_gate", None)
                project.save()
            produce_queue.cancel(item_id)
            if item["status"] != "running":
                _set_status(item["project_id"], state="cancelled", message="Cancelled by user.")
        elif action == "retry":
            produce_queue.retry(item_id)
        elif action == "restart":
            produce_queue.restart(item_id)
        elif action == "recut":
            produce_queue.recut(item_id)
        elif action == "move":
            produce_queue.move(item_id, (payload.direction if payload else None) or "up")
        elif action == "remove":
            produce_queue.remove(item_id)
    except ValueError as exc:
        if action in ("retry", "restart", "recut", "resume") and item["status"] != "running":
            _set_status(item["project_id"], **previous_status)
        raise HTTPException(status_code=409, detail=str(exc))
    return _queue_view()


# ─────────────────────────── Entry B: BuzzEdit drives ───────────────────────────


class ProducePlanSchema(BaseModel):
    brand: str
    script_text: Optional[str] = None
    transcript: Optional[str] = None


@router.post("/api/produce/plan")
def produce_plan(payload: ProducePlanSchema):
    """A synchronous plan request from BuzzEdit (or anyone else): given a
    script or a transcript and a brand, return the directive-annotated
    script, the derived BuzzEdit settings, and the raw visual plan."""
    text = (payload.script_text or payload.transcript or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="script_text or transcript is required.")

    from core.agent import AgentFactory
    from integrations.llm import LLMService, clean_json_response
    from runtime.workflow import VISUAL_PLAN_JSON_INSTRUCTION

    agent = AgentFactory.get_agent("PromptEngineer", LLMService(purpose="production"))
    raw = agent.execute(text + "\n\n" + VISUAL_PLAN_JSON_INSTRUCTION, require_json=True)
    try:
        visual_plan = json.loads(clean_json_response(str(raw)))
    except Exception:
        raise HTTPException(status_code=502, detail="The model did not return a usable visual plan.")

    annotated_text, skipped = to_directive_script(text, visual_plan)
    settings = settings_for_brand(payload.brand)
    return {
        "annotated_script": annotated_text,
        "settings": settings,
        "visual_plan": visual_plan,
        "skipped_beats": skipped,
    }
