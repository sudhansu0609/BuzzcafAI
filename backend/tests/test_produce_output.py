"""Where the finished video goes (`produce_api._deliver_output`): next to the
recording by default, named after it with `_final`; one folder for all; or left
where BuzzEdit wrote it. The reveal endpoint shows it in Explorer."""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import app
from core.models.project import Project


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project(tmp_path):
    p = Project(id="out_proj", name="Meri Dadi: Ek Kursi", brand="Raat3Baje", workflow_name="khayal3baje_horror")
    rec_dir = tmp_path / "ep3"
    rec_dir.mkdir()
    recording = rec_dir / "ep3tremp1.mp4"
    recording.write_bytes(b"recording")
    p.metadata["recording_path"] = str(recording)
    p.save()
    yield p, rec_dir
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)


def _settings(monkeypatch, **cfg):
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: dict(cfg))


def _render(tmp_path):
    out = tmp_path / "buzzedit" / "out"
    out.mkdir(parents=True)
    rendered = out / "25eff765_output.mp4"
    rendered.write_bytes(b"x" * 1000)
    return str(rendered)


def test_default_is_next_to_the_recording_named_after_it(project, tmp_path, monkeypatch):
    p, rec_dir = project
    _settings(monkeypatch)
    rendered = _render(tmp_path)
    final, warning = produce_api._deliver_output(p, rendered)
    assert warning is None
    assert final == str(rec_dir / "ep3tremp1_final.mp4")
    assert os.path.getsize(final) == 1000
    assert os.path.isfile(rendered)  # BuzzEdit's file stays for re-renders and publishing
    # A second delivery of the same render does not rewrite the copy.
    before = os.path.getmtime(final)
    assert produce_api._deliver_output(p, rendered) == (final, None)
    assert os.path.getmtime(final) == before


def test_one_folder_for_every_video(project, tmp_path, monkeypatch):
    p, _ = project
    finals = tmp_path / "finals"
    finals.mkdir()
    _settings(monkeypatch, produce_output_mode="folder", produce_output_dir=str(finals))
    final, warning = produce_api._deliver_output(p, _render(tmp_path))
    assert warning is None and final == str(finals / "ep3tremp1_final.mp4")


def test_a_missing_folder_leaves_the_render_where_it_is(project, tmp_path, monkeypatch):
    p, _ = project
    _settings(monkeypatch, produce_output_mode="folder", produce_output_dir=str(tmp_path / "nope"))
    assert produce_api._deliver_output(p, _render(tmp_path)) == (None, None)


def test_buzzedit_mode_copies_nothing(project, tmp_path, monkeypatch):
    p, rec_dir = project
    _settings(monkeypatch, produce_output_mode="buzzedit")
    assert produce_api._deliver_output(p, _render(tmp_path)) == (None, None)
    assert not (rec_dir / "ep3tremp1_final.mp4").exists()


def test_a_project_without_a_recording_path_uses_its_own_folder(project, tmp_path, monkeypatch):
    p, _ = project
    p.metadata.pop("recording_path")
    p.save()
    _settings(monkeypatch)
    final, warning = produce_api._deliver_output(p, _render(tmp_path))
    assert warning is None
    assert final.startswith(os.path.join(p.get_project_dir(), "production"))
    assert final.endswith("_final.mp4")


def test_a_copy_failure_is_a_warning_not_a_failed_run(project, tmp_path, monkeypatch):
    p, _ = project
    _settings(monkeypatch)
    rendered = _render(tmp_path)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", boom)
    final, warning = produce_api._deliver_output(p, rendered)
    assert final is None and "disk full" in warning and rendered in warning


def test_reveal_endpoint_prefers_the_final_copy(project, tmp_path, monkeypatch, client):
    p, rec_dir = project
    rendered = _render(tmp_path)
    final = rec_dir / "ep3tremp1_final.mp4"
    final.write_bytes(b"f")
    p.metadata["output_path"] = rendered
    p.metadata["final_output_path"] = str(final)
    p.save()
    opened = []
    monkeypatch.setattr(produce_api.sys, "platform", "win32")
    monkeypatch.setattr(produce_api.subprocess, "Popen", lambda args, **k: opened.append(args))
    r = client.post(f"/api/projects/{p.id}/produce_video/reveal")
    assert r.status_code == 200 and r.json()["path"] == str(final)
    assert opened and opened[0][0] == "explorer.exe" and str(final) in opened[0][1]

    p.metadata.pop("final_output_path")
    p.metadata["output_path"] = str(tmp_path / "gone.mp4")
    p.save()
    assert client.post(f"/api/projects/{p.id}/produce_video/reveal").status_code == 404
