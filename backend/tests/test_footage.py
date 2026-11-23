"""Own-footage mode (docs/OWN_FOOTAGE_PLAN.md): shot tags, the catalog cache, the plan."""
from types import SimpleNamespace

from app.services import footage
from integrations.buzzedit_script import _directive_for


def _project(tmp_path):
    return SimpleNamespace(metadata={"footage_dir": str(tmp_path / "clips")}, get_project_dir=lambda: str(tmp_path / "proj"))


def test_shot_tags_and_script_spans():
    assert [footage.parse_shot(n) for n in ("shot06_notebook.mp4", "s6.mov", "sh-6.mp4", "scene2_car.mp4", "desk.mp4")] == [6, 6, 6, 2, None]
    script = 'Shot 1\nCamera: desk\n"Mera naam hai Sudhansu aur main software banata hoon"\nSHOT 2\n"Phir ek din maine notebook khola aur likhna shuru kiya"'
    said = ("mera naam hai sudhansu aur main software banata hoon phir ek din maine notebook khola aur likhna shuru kiya").split()
    words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(said)]
    spans = footage.shot_spans(script, words)
    assert spans[1]["word_start"] == 0 and spans[2]["word_start"] == 9


def test_catalog_cache_keeps_notes_and_skips_unchanged(tmp_path, monkeypatch):
    project = _project(tmp_path)
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "shot03_desk.mp4").write_bytes(b"x")
    calls = []

    def fake_read(proj, path, previous):
        calls.append(path)
        if previous and previous.get("description"):
            return previous
        return {"id": "shot03-desk", "name": "shot03_desk.mp4", "path": path.replace("\\", "/"), "shot": 3,
                "duration": 8.0, "description": {"what": "a desk"}, "error": None}

    monkeypatch.setattr(footage, "_read_clip", fake_read)
    first = footage.catalog(project)
    first[0]["note"] = "my desk"
    footage._save_catalog(project, first)
    again = footage.catalog(project)
    assert again[0]["note"] == "my desk" and again[0]["description"] == {"what": "a desk"}


def test_own_plan_keeps_idea_pictures_under_the_cap():
    clips = [{"id": "a", "path": "C:/c/a.mp4", "duration": 10.0, "description": {"what": "a desk"}}]
    beats = [{"kind": "own_clip", "clip": "a", "in": 0.5, "seconds": 6, "start": 1.0, "end": 7.0},
             {"kind": "broll_image", "image_prompt": "a crowded idea board", "start": 8.0, "end": 11.0},
             {"kind": "broll_video", "video_prompt": "a city of the future", "start": 12.0, "end": 20.0}]
    out, _ = footage.finalize_beats(beats, clips)
    # 6 s of his clip vs 11 s generated: the latest idea picture goes, 3 s / 9 s stays under 40%.
    assert [b["kind"] for b in out] == ["own_clip", "broll_image"]


def test_own_plan_has_own_clips_idea_pictures_and_graphics():
    clips = [{"id": "a", "path": "C:/c/a.mp4", "duration": 10.0, "description": {"what": "a desk"}},
             {"id": "b", "path": "C:/c/b.mp4", "duration": 9.0, "description": {"what": "a car"}}]
    beats = [{"kind": "own_clip", "clip": "a", "in": 0.5, "seconds": 6, "start": 1.0, "end": 7.0, "anchor": "desk"},
             {"kind": "broll_image", "image_prompt": "x", "start": 8.0, "end": 9.0},
             {"kind": "broll_video", "video_prompt": "y", "start": 9.0, "end": 12.0},
             {"kind": "own_clip", "clip": "ghost", "start": 13.0, "end": 14.0},
             {"kind": "statement_card", "text": "Start", "start": 20.0, "end": 22.0}]
    out, unused = footage.finalize_beats(beats, clips)
    assert [b["kind"] for b in out] == ["own_clip", "broll_image", "broll_video", "statement_card"] and unused == ["b"]
    line = _directive_for(out[0])
    assert line.startswith("[video: ") and "own=C:/c/a.mp4" in line and "in=0.5" in line and "seconds=6" in line
    print(line)
