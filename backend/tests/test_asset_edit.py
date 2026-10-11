"""The teleprompter's script round-trip: take a script asset out, rectify it,
put it back. The previous text is kept under history/, and only text assets
inside the project can be written."""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.models.project import Project

PID = "asset_edit_test_proj"


@pytest.fixture
def project():
    p = Project(id=PID, name="Asset Edit", brand="Raat3Baje", workflow_name="after_dark_narration")
    p.save()
    folder = os.path.join(p.get_project_dir(), "script")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "final.md"), "w", encoding="utf-8") as f:
        f.write("Pehla draft. (pause) Raat ke teen baje.")
    with open(os.path.join(p.get_project_dir(), "plan.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    p.assets.update({"script_final": "script/final.md", "plan": "plan.json", "escape": "../outside.md"})
    p.save()
    yield p
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)


def test_an_edited_script_is_put_back_and_the_old_one_kept(project):
    c = TestClient(app)
    url = f"/api/projects/{PID}/asset/script_final"
    r = c.put(url, json={"content": "Sudhara hua draft.\r\n(slow) Raat ke teen baje."})
    assert r.status_code == 200 and r.json()["status"] == "saved"
    assert c.get(url).json()["content"] == "Sudhara hua draft.\n(slow) Raat ke teen baje."
    backup = os.path.join(project.get_project_dir(), r.json()["backup"])
    with open(backup, encoding="utf-8") as f:
        assert f.read() == "Pehla draft. (pause) Raat ke teen baje."
    assert Project.load(PID).metadata["asset_edits"]["script_final"]["backup"].startswith("script/history/")
    # Saving the same text again changes nothing.
    assert c.put(url, json={"content": "Sudhara hua draft.\n(slow) Raat ke teen baje."}).json()["status"] == "unchanged"


def test_only_text_assets_inside_the_project_can_be_written(project):
    c = TestClient(app)
    assert c.put(f"/api/projects/{PID}/asset/plan", json={"content": "x"}).status_code == 400
    assert c.put(f"/api/projects/{PID}/asset/escape", json={"content": "x"}).status_code == 400
    assert c.put(f"/api/projects/{PID}/asset/missing", json={"content": "x"}).status_code == 404
    assert c.put(f"/api/projects/{PID}/asset/script_final", json={"content": "   "}).status_code == 400
    assert c.put("/api/projects/no_such_proj/asset/script_final", json={"content": "x"}).status_code == 404
