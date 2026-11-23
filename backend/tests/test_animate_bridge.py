from types import SimpleNamespace

from app.services import animate_bridge as ab
from runtime.workflow import _condition_holds


def test_not_animated_condition():
    assert not _condition_holds(SimpleNamespace(brand="Khayal3Baje", metadata={}), "not_animated")
    assert not _condition_holds(SimpleNamespace(brand="Originals", metadata={}), "not_animated")
    assert _condition_holds(SimpleNamespace(brand="Raat3Baje", metadata={}), "not_animated")


def test_command_flags(tmp_path, monkeypatch):
    (tmp_path / "s.md").write_text("INT. ROOM - NIGHT\nNARRATOR (V.O.): hi", encoding="utf-8")
    proj = SimpleNamespace(brand="Originals", assets={"screenplay": "s.md"}, metadata={},
                           get_project_dir=lambda: str(tmp_path))
    monkeypatch.setattr(ab, "_config", lambda: {"animate_root": str(tmp_path)})
    cmd, cwd = ab.command(proj, "Originals", str(tmp_path / "out"))
    assert "--mp4" in cmd and "--launch-comfy" in cmd
    assert cmd[cmd.index("--style") + 1] == "comic" and "--world" in cmd and cwd == str(tmp_path)
