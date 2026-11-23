"""The synthetic take: a recording built by the Studio, not filmed.

Every BuzzEdit production starts from a recording. For a video made end to
end by the tool (AUTO_STORY_PLAN.md §2, §3.2) the Studio builds one: the
creator's face-intro clip (per channel, optional) followed by the narration
audio over a still frame, in the orientation the format needs. The existing
pipeline then runs unchanged on it.

ffmpeg only. Both parts are encoded with the same codec parameters (H.264
high, yuv420p, 30 fps, AAC 48 kHz stereo) so the concat demuxer joins them
without re-encoding.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import wave
from datetime import datetime
from typing import Any, Dict, List, Optional

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

logger = logging.getLogger(__name__)

FRAME_SIZES = {"landscape": (1920, 1080), "vertical": (1080, 1920)}
FPS = 30
SAMPLE_RATE = 48000
STILL_COLOR = "0x141418"  # rgb(20, 20, 24)
MIN_NARRATION_S = 0.5

# Identical on both parts, so the join is a stream copy.
_VIDEO_CODEC = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
    "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
    "-r", str(FPS), "-video_track_timescale", "15360",
]
_AUDIO_CODEC = ["-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE), "-ac", "2"]


def _fit_filter(width: int, height: int) -> str:
    """Scale to fit the frame, pad with black, square pixels, 30 fps."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={FPS},format=yuv420p"
    )


def _run(cmd: List[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{cmd[0]} timed out after {timeout:.0f}s") from exc
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[-2000:]
        raise RuntimeError(f"{cmd[0]} failed (exit {proc.returncode}): {err}")
    return proc


def _probe_duration(path: str) -> float:
    """The container duration in seconds (ffprobe), 0 when unreadable."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW)
        return max(0.0, float((proc.stdout or "").strip().splitlines()[0]))
    except Exception:  # noqa: BLE001 - unreadable media counts as no duration
        return 0.0


def _has_audio(path: str) -> bool:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW)
        return bool((proc.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return False


def _wav_duration(path: str) -> float:
    """PCM wav length from its header; ffprobe for anything wave can't read."""
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            if rate > 0:
                return w.getnframes() / float(rate)
    except Exception:  # noqa: BLE001 - float or odd wavs: ask ffprobe
        pass
    return _probe_duration(path)


def face_intro_clip_for(brand: str) -> Optional[str]:
    """The channel's face-intro clip: config `channel_formats[brand]["face_intro_clip"]`,
    only when the file exists."""
    try:
        from integrations.llm import load_config
        table = load_config().get("channel_formats") or {}
    except Exception:  # noqa: BLE001 - unreadable settings: no clip
        return None
    if not isinstance(table, dict):
        return None
    entry = table.get(brand)
    if entry is None and brand:
        for key, value in table.items():
            if str(key).lower() == str(brand).lower():
                entry = value
                break
    if not isinstance(entry, dict):
        return None
    clip = entry.get("face_intro_clip")
    if not clip or not isinstance(clip, str):
        return None
    if not os.path.isfile(clip):
        logger.warning("Face intro clip for %s not found: %s", brand, clip)
        return None
    return os.path.abspath(clip)


def _intro_cmd(clip: str, out: str, width: int, height: int, duration: float, has_audio: bool) -> List[str]:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", clip]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={SAMPLE_RATE}"]
    cmd += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0"]
    cmd += ["-vf", _fit_filter(width, height), "-af", f"aresample={SAMPLE_RATE}"]
    cmd += _VIDEO_CODEC + _AUDIO_CODEC
    cmd += ["-t", f"{duration:.3f}", out]
    return cmd


def _narration_cmd(wav: str, still: Optional[str], out: str, width: int, height: int,
                   duration: float, faststart: bool) -> List[str]:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if still:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-i", still]
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c={STILL_COLOR}:s={width}x{height}:r={FPS}"]
    cmd += ["-i", wav, "-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-vf", _fit_filter(width, height), "-af", f"aresample={SAMPLE_RATE}"]
    cmd += _VIDEO_CODEC + _AUDIO_CODEC
    if faststart:
        cmd += ["-movflags", "+faststart"]
    cmd += ["-t", f"{duration:.3f}", out]
    return cmd


def _concat_cmd(list_file: str, out: str) -> List[str]:
    return [
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", "-movflags", "+faststart", out,
    ]


def build_take(project: Any, narration_wav: str, *, orientation: str,
               face_intro_clip: Optional[str] = None, still: Optional[str] = None,
               out_dir: Optional[str] = None) -> Dict[str, Any]:
    """Build `<project>/recording/take_<stamp>.mp4`: the face intro (if any),
    then the narration over a still of exactly the narration's length.

    Returns {"path", "duration_s", "face_intro_s", "orientation"}.
    """
    if orientation not in FRAME_SIZES:
        raise ValueError(f"orientation must be 'landscape' or 'vertical', not {orientation!r}")
    width, height = FRAME_SIZES[orientation]

    if not narration_wav or not os.path.isfile(narration_wav):
        raise FileNotFoundError(f"Narration wav not found: {narration_wav}")
    narration_s = _wav_duration(narration_wav)
    if narration_s <= MIN_NARRATION_S:
        raise ValueError(f"Narration is too short ({narration_s:.2f}s): {narration_wav}")

    if face_intro_clip and not os.path.isfile(face_intro_clip):
        logger.warning("Face intro clip not found, building the take without it: %s", face_intro_clip)
        face_intro_clip = None
    if still and not os.path.isfile(still):
        logger.warning("Still image not found, using the dark frame: %s", still)
        still = None

    intro_s = _probe_duration(face_intro_clip) if face_intro_clip else 0.0
    if face_intro_clip and intro_s <= 0:
        logger.warning("Face intro clip has no readable duration, skipping it: %s", face_intro_clip)
        face_intro_clip = None
        intro_s = 0.0

    target_dir = out_dir or os.path.join(project.get_project_dir(), "recording")
    os.makedirs(target_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    final = os.path.abspath(os.path.join(target_dir, f"take_{stamp}.mp4"))
    narration_timeout = 600 + 2 * narration_s

    if not face_intro_clip:
        _run(_narration_cmd(narration_wav, still, final, width, height, narration_s, True), narration_timeout)
    else:
        intro_part = os.path.join(target_dir, f".take_{stamp}_intro.mp4")
        story_part = os.path.join(target_dir, f".take_{stamp}_narration.mp4")
        list_file = os.path.join(target_dir, f".take_{stamp}_concat.txt")
        try:
            _run(_intro_cmd(face_intro_clip, intro_part, width, height, intro_s,
                            _has_audio(face_intro_clip)), 600 + 4 * intro_s)
            _run(_narration_cmd(narration_wav, still, story_part, width, height, narration_s, False),
                 narration_timeout)
            with open(list_file, "w", encoding="utf-8") as fh:
                for part in (intro_part, story_part):
                    safe = os.path.abspath(part).replace("\\", "/").replace("'", "'\\''")
                    fh.write(f"file '{safe}'\n")
            _run(_concat_cmd(list_file, final), 600)
        finally:
            for tmp in (intro_part, story_part, list_file):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    duration = _probe_duration(final) or (intro_s + narration_s)
    logger.info("Synthetic take built: %s (%.1fs, intro %.1fs, %s)", final, duration, intro_s, orientation)
    return {
        "path": final,
        "duration_s": round(duration, 3),
        "face_intro_s": round(intro_s, 3),
        "orientation": orientation,
    }
