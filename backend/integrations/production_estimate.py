"""How many clips and stills a production will need, and how long it will take.

Shown under the Video / Images / Face sliders on the Projects page. The page
does the arithmetic live as the sliders move; this module supplies the inputs:
the video's running time and the machine's measured speeds.

Speeds are calibrated from the newest finished render that made clips (its
BuzzEdit report times the asset stage and the render), falling back to the
baselines measured on the RTX 5060 Ti 16 GB box.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from core.paths import PROJECTS_DIR

#: Fallback speeds (seconds), measured 2026-09/10 on the reference machine.
DEFAULT_SPEEDS = {
    "still_s": 21.4,        # one Z-Image still
    "clip_s": 210.0,        # one Wan 2.2 i2v clip (its starting still not included)
    "render_factor": 0.75,  # final render time / video running time
    "fixed_s": 12 * 60,     # transcription, planning, shot plan, face pass, Shorts
}
#: Average shot lengths the story planner produces.
CLIP_SECONDS = 5.0
STILL_SECONDS = 4.0
#: Speaking rate used when only the script exists (Hinglish narration measured ~155 wpm).
WORDS_PER_MINUTE = 150.0


def _report_speeds(report: Dict[str, Any]) -> Optional[Dict[str, float]]:
    timings = {t.get("stage"): float(t.get("seconds") or 0) for t in report.get("timings") or [] if isinstance(t, dict)}
    phase = ((report.get("generation") or {}).get("video_phase") or {})
    made = int(phase.get("made") or 0)
    pictures = int(report.get("assets_generated") or 0)
    assets_s = timings.get("assets") or 0.0
    if made <= 0 or assets_s <= 0:
        return None
    clip_s = (assets_s - pictures * DEFAULT_SPEEDS["still_s"]) / made
    if not 60 <= clip_s <= 1200:          # a stalled or cached run says nothing useful
        return None
    out = {"clip_s": round(clip_s, 1)}
    runtime = (report.get("program") or {}).get("duration_s")
    if timings.get("render") and runtime:
        out["render_factor"] = round(timings["render"] / float(runtime), 2)
    return out


def measured_speeds() -> Dict[str, Any]:
    """Speeds from the newest render with clips, else the baselines."""
    speeds = dict(DEFAULT_SPEEDS)
    source = "baseline"
    newest = None
    try:
        for name in os.listdir(PROJECTS_DIR):
            path = os.path.join(PROJECTS_DIR, name, "project.json")
            try:
                report = (json.load(open(path, encoding="utf-8")).get("metadata") or {}).get("buzzedit_report")
            except (OSError, ValueError):
                continue
            if not isinstance(report, dict):
                continue
            finished = str(report.get("finished_at") or "")
            if newest is None or finished > newest[0]:
                found = _report_speeds(report)
                if found:
                    newest = (finished, found)
    except OSError:
        pass
    if newest:
        speeds.update(newest[1])
        source = f"last render ({newest[0][:10]})"
    return {**speeds, "source": source}


def runtime_for(project: Any) -> Dict[str, Any]:
    """The running time to plan for: the finished edit, else the recording's
    duration, else the script read at a speaking pace."""
    meta = project.metadata or {}
    achieved = meta.get("runtime_mix_achieved") or {}
    if achieved.get("runtime_s"):
        return {"seconds": float(achieved["runtime_s"]), "source": "your recording (last render)"}
    report = meta.get("buzzedit_report") if isinstance(meta.get("buzzedit_report"), dict) else {}
    if (report.get("program") or {}).get("duration_s"):
        return {"seconds": float(report["program"]["duration_s"]), "source": "your recording (last render)"}
    assets = project.assets or {}
    for key in ("narration_optimized", "script_final", "script"):
        if not assets.get(key):
            continue
        path = os.path.join(project.get_project_dir(), assets[key])
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        words = len(re.findall(r"[\w']+", re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)))
        if words > 50:
            return {"seconds": round(words / WORDS_PER_MINUTE * 60.0, 1), "source": f"script ({words} words)"}
    return {"seconds": 0.0, "source": "unknown"}


def estimate(runtime_s: float, video: float, images: float, speeds: Dict[str, Any]) -> Dict[str, Any]:
    """Same arithmetic the Projects page runs live (kept here for tests and reports)."""
    video_s, image_s = runtime_s * video, runtime_s * images
    clips = round(video_s / CLIP_SECONDS)
    stills = round(image_s / STILL_SECONDS)
    pictures_s = (clips + stills) * speeds["still_s"]      # every clip starts from a still
    clips_s = clips * speeds["clip_s"]
    render_s = runtime_s * speeds["render_factor"]
    total = pictures_s + clips_s + render_s + speeds["fixed_s"]
    return {"clips": clips, "stills": stills, "pictures_s": round(pictures_s), "clips_s": round(clips_s),
            "render_s": round(render_s), "fixed_s": round(speeds["fixed_s"]), "total_s": round(total)}
