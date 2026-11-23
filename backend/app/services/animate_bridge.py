"""Studio -> BuzzAnimate producer (ANIMATED_CHANNELS_PLAN ST1).

Khayal3Baje and Originals projects are animated, not made of BuzzEdit stills.
`produce(project_id)` runs BuzzAnimate's producer CLI (see
BuzzAnimate/docs/PRODUCER_HOWTO.md) on the project's `screenplay` asset as a
background job that holds the one-video slot, streams the producer's log to
`<project>/production/animation/producer.log`, records progress in
`project.metadata["animation"]` and, on success, sets
`metadata["output_path"]` to the episode mp4.

Config keys: `animate_root`, `animate_character_dirs` {brand: dir},
`animate_worlds` {brand: text}.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import subprocess
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from core.models.project import Project

logger = logging.getLogger("buzzcaf_ai.animate_bridge")

DEFAULT_ROOT = r"B:\youtubeProjects\Buzzcaf_Media\BuzzAnimate"
BRANDS = {"khayal3baje": "Khayal3Baje", "originals": "Originals"}
STYLES = {"Khayal3Baje": "painterly", "Originals": "comic"}
DEFAULT_WORLDS = {"Originals": "a semi-rural small town in North India, 2010s"}

_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def canonical_brand(project: Project) -> Optional[str]:
    return BRANDS.get((project.brand or "").strip().lower())


def _config() -> Dict[str, Any]:
    from integrations.llm import load_config
    return load_config()


def screenplay_path(project: Project) -> Optional[str]:
    rel = project.assets.get("screenplay")
    full = os.path.join(project.get_project_dir(), rel) if rel else None
    return full if full and os.path.isfile(full) else None


def audio_path(project: Project) -> Optional[str]:
    rec = str(project.metadata.get("recording_path") or "")
    if rec and os.path.isfile(rec):
        return rec
    wav = os.path.join(project.get_project_dir(), "audio", "narration.wav")
    return wav if os.path.isfile(wav) else None


def prepare_characters(project: Project, chars: str) -> None:
    """Cast from production/cast.json (ST2): a member with a folder in the brand's
    characters dir uses it; without one, a description.txt (look, clothes, age) is
    written there. The screenplay's first action line for each character carries
    the same look, since the producer reads the script for unpictured characters."""
    path = os.path.join(project.get_project_dir(), "production", "cast.json")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            cast = json.load(f)
        for c in cast:
            name = str(c.get("name") or "").strip()
            if not name or os.path.isdir(os.path.join(chars, name)):
                continue
            d = os.path.join(chars, name)
            os.makedirs(d, exist_ok=True)
            lines = [f"{k}: {c[k]}" for k in ("age", "gender", "look", "clothes") if c.get(k)]
            with open(os.path.join(d, "description.txt"), "w", encoding="utf-8") as f:
                f.write(chr(10).join(lines) + chr(10))
    except Exception:  # noqa: BLE001 - the run goes on with the screenplay's own descriptions
        logger.exception("animate_bridge: could not prepare the cast folders")


def command(project: Project, brand: str, out_dir: str) -> tuple:
    """The producer CLI call and its working directory."""
    cfg = _config()
    root = str(cfg.get("animate_root") or DEFAULT_ROOT)
    exe = os.path.join(root, "target", "release", "examples", "produce.exe")
    if os.path.isfile(exe):
        cmd = [exe]
    else:
        cmd = ["cargo", "run", "--release", "-p", "buzz-app", "--example", "produce", "--"]
    cmd += ["--script", screenplay_path(project) or ""]
    audio = audio_path(project)
    if audio:
        cmd += ["--audio", audio]
    chars = (cfg.get("animate_character_dirs") or {}).get(brand) or os.path.join(
        r"B:\youtubeProjects", brand, "characters")
    if os.path.isdir(chars):
        prepare_characters(project, chars)
        cmd += ["--characters", chars]
    cmd += ["--style", STYLES[brand], "--series", brand]
    world = (cfg.get("animate_worlds") or {}).get(brand) or DEFAULT_WORLDS.get(brand)
    if world:
        cmd += ["--world", world]
    cmd += ["--out", out_dir, "--mp4", "--launch-comfy"]
    return cmd, root


def status(project_id: str) -> Dict[str, Any]:
    try:
        project = Project.load(project_id)
    except Exception:  # noqa: BLE001
        return {"state": "idle"}
    stored = dict(project.metadata.get("animation") or {})
    with _lock:
        live = next((dict(j) for j in _jobs.values() if j["project_id"] == project_id), None)
    out = live or stored or {"state": "idle"}
    out["has_screenplay"] = bool(screenplay_path(project))
    return out


def _record(project_id: str, job: Dict[str, Any], **fields: Any) -> None:
    job.update(fields)
    try:
        project = Project.load(project_id)
        project.metadata["animation"] = {k: v for k, v in job.items() if k != "project_id"}
        if fields.get("output_path"):
            project.metadata["output_path"] = fields["output_path"]
        project.save()
    except Exception:  # noqa: BLE001 - a record write never kills the run
        logger.exception("animate_bridge: could not record status for %s", project_id)


def _run(project_id: str, job: Dict[str, Any], cmd: list, cwd: str, out_dir: str, brand: str, title: str) -> None:
    from app.services import master_control, video_slot
    log_path = os.path.join(out_dir, "producer.log")
    try:
        master_control.wait_if_paused(f"animate_bridge: {project_id}")
        with video_slot.turn(project_id, title=title, brand=brand, what="animation",
                             say=lambda m: _record(project_id, job, message=m)):
            _record(project_id, job, state="running", message="Producing the animation...", started_at=_now())
            os.makedirs(out_dir, exist_ok=True)
            with open(log_path, "w", encoding="utf-8", errors="replace") as log:
                log.write(" ".join(cmd) + "\n")
                log.flush()
                proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace")
                last = ""
                for line in proc.stdout:  # type: ignore[union-attr]
                    log.write(line)
                    log.flush()
                    if line.strip():
                        last = line.strip()[:200]
                        job["message"] = last
                code = proc.wait()
            if code != 0:
                raise RuntimeError(f"The producer exited with code {code}: {last}")
            mp4s = sorted(glob.glob(os.path.join(out_dir, "**", "*.mp4"), recursive=True),
                          key=os.path.getmtime, reverse=True)
            if not mp4s:
                raise RuntimeError("The producer finished but wrote no .mp4.")
            _record(project_id, job, state="done", message="Animation ready.", output_path=mp4s[0],
                    finished_at=_now())
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        logger.exception("animate_bridge %s failed", project_id)
        _record(project_id, job, state="failed", error=str(exc)[:300], message=f"Failed: {str(exc)[:120]}",
                finished_at=_now())


def produce(project_id: str) -> Dict[str, Any]:
    """Start the producer as a background job; returns the job record."""
    project = Project.load(project_id)
    brand = canonical_brand(project)
    if not brand:
        raise ValueError("Only Khayal3Baje and Originals projects are animated.")
    if not screenplay_path(project):
        raise ValueError("This project has no screenplay yet; run the Animation Screenplay step first.")
    with _lock:
        if any(j["project_id"] == project_id and j["state"] in ("queued", "running") for j in _jobs.values()):
            raise RuntimeError("This project is already being animated.")
        job = {"job_id": uuid.uuid4().hex[:12], "project_id": project_id, "state": "queued",
               "message": "Waiting to start", "error": None, "output_path": None,
               "log_path": None, "queued_at": _now()}
        _jobs[job["job_id"]] = job
    out_dir = os.path.join(project.get_project_dir(), "production", "animation")
    job["log_path"] = os.path.join(out_dir, "producer.log")
    cmd, cwd = command(project, brand, out_dir)
    _record(project_id, job)
    threading.Thread(target=_run, args=(project_id, job, cmd, cwd, out_dir, brand, project.name),
                     name=f"animate-bridge-{project_id}", daemon=True).start()
    return job
