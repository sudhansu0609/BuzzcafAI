"""The synthetic take (AUTO_STORY_PLAN.md §3.2): face intro + narration over a still."""
import os
import shutil
import subprocess
import wave

import pytest

from integrations import synthetic_take


class _Project:
    def __init__(self, root):
        self.root = str(root)

    def get_project_dir(self):
        return self.root


def _write_wav(path, seconds=1.0, rate=48000):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames)
    return str(path)


@pytest.fixture
def recorder(monkeypatch):
    """Fake subprocess.run: records commands, answers ffprobe, touches ffmpeg outputs."""
    calls = []
    state = {"duration": "5.000000", "audio": "1"}

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        out = ""
        if cmd[0] == "ffprobe":
            out = state["audio"] if "-select_streams" in cmd else state["duration"]
        elif cmd[0] == "ffmpeg":
            with open(cmd[-1], "wb") as fh:
                fh.write(b"x")
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(synthetic_take.subprocess, "run", fake_run)
    return calls, state


def _ffmpeg(calls):
    return [c for c in calls if c[0] == "ffmpeg"]


def test_still_only_take(tmp_path, recorder):
    calls, _ = recorder
    wav = _write_wav(tmp_path / "n.wav", 2.0)
    result = synthetic_take.build_take(_Project(tmp_path / "proj"), wav, orientation="vertical",
                                       face_intro_clip=None)
    ff = _ffmpeg(calls)
    assert len(ff) == 1
    cmd = ff[0]
    assert cmd[:4] == ["ffmpeg", "-y", "-loglevel", "error"]
    assert any(a.startswith("color=c=0x141418:s=1080x1920:r=30") for a in cmd)
    assert cmd[cmd.index("-t") + 1] == "2.000"
    assert "yuv420p" in cmd and "aac" in cmd and "48000" in cmd
    assert result["face_intro_s"] == 0
    assert result["orientation"] == "vertical"
    folder = os.path.join(str(tmp_path / "proj"), "recording")
    assert os.path.dirname(result["path"]) == os.path.abspath(folder)
    assert os.path.basename(result["path"]).startswith("take_")
    assert result["path"].endswith(".mp4")


def test_intro_then_narration_joined(tmp_path, recorder):
    calls, state = recorder
    wav = _write_wav(tmp_path / "n.wav", 1.5)
    clip = tmp_path / "intro.mov"
    clip.write_bytes(b"clip")
    still = tmp_path / "s.png"
    still.write_bytes(b"png")
    state["duration"] = "4.250000"
    result = synthetic_take.build_take(_Project(tmp_path), wav, orientation="landscape",
                                       face_intro_clip=str(clip), still=str(still))
    ff = _ffmpeg(calls)
    assert len(ff) == 3
    intro, story, join = ff
    assert str(clip) in intro
    assert any("scale=1920:1080:force_original_aspect_ratio=decrease" in a for a in intro)
    assert intro[intro.index("-map", intro.index("-map") + 1) + 1] == "0:a:0"
    assert "-loop" in story and str(still) in story
    assert story[story.index("-t") + 1] == "1.500"
    # identical codec parameters on both parts
    assert intro[intro.index("-c:v"):intro.index("-t")] == story[story.index("-c:v"):story.index("-t")]
    assert join[join.index("-f") + 1] == "concat" and join[join.index("-c") + 1] == "copy"
    assert result["face_intro_s"] == 4.25
    # temporary parts removed
    left = [n for n in os.listdir(os.path.dirname(result["path"])) if n.startswith(".take_")]
    assert left == []


def test_intro_without_audio_gets_silence(tmp_path, recorder):
    calls, state = recorder
    wav = _write_wav(tmp_path / "n.wav", 1.0)
    clip = tmp_path / "intro.mp4"
    clip.write_bytes(b"clip")
    state["audio"] = ""
    synthetic_take.build_take(_Project(tmp_path), wav, orientation="landscape", face_intro_clip=str(clip))
    intro = _ffmpeg(calls)[0]
    assert any(a.startswith("anullsrc=") for a in intro)
    assert "1:a:0" in intro


def test_missing_intro_is_none(tmp_path, recorder):
    calls, _ = recorder
    wav = _write_wav(tmp_path / "n.wav", 1.0)
    result = synthetic_take.build_take(_Project(tmp_path), wav, orientation="landscape",
                                       face_intro_clip=str(tmp_path / "nope.mp4"))
    assert len(_ffmpeg(calls)) == 1
    assert result["face_intro_s"] == 0


def test_out_dir_used(tmp_path, recorder):
    wav = _write_wav(tmp_path / "n.wav", 1.0)
    out = tmp_path / "elsewhere"
    result = synthetic_take.build_take(_Project(tmp_path / "p"), wav, orientation="landscape",
                                       face_intro_clip=None, out_dir=str(out))
    assert os.path.dirname(result["path"]) == os.path.abspath(str(out))


def test_validation(tmp_path, recorder):
    with pytest.raises(FileNotFoundError):
        synthetic_take.build_take(_Project(tmp_path), str(tmp_path / "x.wav"), orientation="vertical",
                                  face_intro_clip=None)
    short = _write_wav(tmp_path / "short.wav", 0.3)
    with pytest.raises(ValueError):
        synthetic_take.build_take(_Project(tmp_path), short, orientation="vertical", face_intro_clip=None)
    ok = _write_wav(tmp_path / "ok.wav", 1.0)
    with pytest.raises(ValueError):
        synthetic_take.build_take(_Project(tmp_path), ok, orientation="square", face_intro_clip=None)


def test_ffmpeg_failure_raises(tmp_path, monkeypatch):
    def failing(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(synthetic_take.subprocess, "run", failing)
    wav = _write_wav(tmp_path / "n.wav", 1.0)
    with pytest.raises(RuntimeError, match="boom"):
        synthetic_take.build_take(_Project(tmp_path), wav, orientation="vertical", face_intro_clip=None)


def test_face_intro_clip_for(tmp_path, monkeypatch):
    clip = tmp_path / "me.mp4"
    clip.write_bytes(b"clip")
    cfg = {"channel_formats": {"Raat3Baje": {"face_intro_clip": str(clip)},
                               "Life3Baje": {"face_intro_clip": str(tmp_path / "gone.mp4")}}}
    monkeypatch.setattr("integrations.llm.load_config", lambda: cfg)
    assert synthetic_take.face_intro_clip_for("Raat3Baje") == os.path.abspath(str(clip))
    assert synthetic_take.face_intro_clip_for("raat3baje") == os.path.abspath(str(clip))
    assert synthetic_take.face_intro_clip_for("Life3Baje") is None
    assert synthetic_take.face_intro_clip_for("Khayal3Baje") is None


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not on PATH")
def test_real_vertical_take(tmp_path):
    wav = _write_wav(tmp_path / "n.wav", 1.0)
    result = synthetic_take.build_take(_Project(tmp_path), wav, orientation="vertical", face_intro_clip=None)
    assert os.path.isfile(result["path"])
    assert abs(result["duration_s"] - 1.0) < 0.15
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", result["path"]],
        capture_output=True, text=True, timeout=60,
    )
    assert probe.stdout.strip() == "1080,1920"
