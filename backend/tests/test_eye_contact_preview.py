"""The Studio's eye-contact Auto mode: measuring the take and the before/after
preview, both done by BuzzEdit (faked here), and the preview file route."""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from app.api import eye_contact_api
from app.main import app
from core.models.project import Project

PID = "eye_preview_test_proj"


@pytest.fixture
def project():
    p = Project(id=PID, name="Eye Preview", brand="Raat3Baje", workflow_name="after_dark_narration")
    p.metadata["buzzedit_project_id"] = "be_1"
    p.save()
    yield p
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)


class FakeBuzzEdit:
    def __init__(self, preview_dir):
        self.analysed, self.previewed = [], []
        self.preview_dir = preview_dir

    def eye_contact_available(self):
        return {"available": True, "reason": ""}

    def get_project(self, pid):
        return {"source_video": r"C:\be\rec.mp4",
                "media_pool": [{"id": "m_rec", "kind": "video", "path": r"C:\be\rec.mp4"}]}

    def start_eye_contact_analyse(self, pid, media_id, setup):
        self.analysed.append((pid, media_id, setup))
        return "analyse1"

    def start_eye_contact_preview(self, pid, media_id, setup, start_s, duration_s):
        self.previewed.append((pid, media_id, setup, start_s, duration_s))
        return f"preview{len(self.previewed)}"

    def eye_contact_status(self, job_id):
        if job_id.startswith("analyse"):
            return {"status": "completed", "progress": 1.0, "stage": "Done",
                    "result": {"auto_measured": True, "measured_shift_deg": 9.4, "camera_look_pct": 12.6,
                               "duration_s": 600.0}}
        n = int(job_id[len("preview"):])
        before = os.path.join(self.preview_dir, f"clip{n}_before.mp4")
        after = os.path.join(self.preview_dir, f"clip{n}_after_abc.mp4")
        sheet = after.replace(".mp4", "_eyes.jpg")
        for path in (before, after, sheet):
            with open(path, "wb") as fh:
                fh.write(b"mp4")
        return {"status": "completed", "progress": 1.0, "stage": "Done",
                "result": {"before_path": before, "after_path": after, "corrected_pct": 88.0,
                           "median_shift_px": 4.2, "auto_measured": True, "lens_source": "measured",
                           "camera_look_candidates": [104.5], "contact_sheet": sheet}}


@pytest.fixture
def preview_dir(tmp_path):
    d = tmp_path / "data" / "cache" / "eyecontact" / "preview"
    d.mkdir(parents=True)
    return str(d)


def test_measuring_stores_the_numbers_on_the_project(project, preview_dir, monkeypatch):
    monkeypatch.setattr(eye_contact_api, "POLL_S", 0)
    be = FakeBuzzEdit(preview_dir)
    stages = []
    result = eye_contact_api.analyse_recording(PID, be, "be_1", lambda s, f: stages.append(s))
    assert be.analysed == [("be_1", "m_rec", {"mode": "auto"})]
    assert result["report"]["measured_shift_deg"] == 9.4
    assert Project.load(PID).metadata["eye_contact_analysis"]["report"]["auto_measured"] is True


def test_preview_measures_first_in_auto_then_cuts_three_moments(project, preview_dir, monkeypatch):
    monkeypatch.setattr(eye_contact_api, "POLL_S", 0)
    be = FakeBuzzEdit(preview_dir)
    clips = eye_contact_api.preview_recording(PID, be, "be_1")
    assert len(be.analysed) == 1                          # measured once, before the clips
    starts = [round(p[3]) for p in be.previewed]
    assert starts == [90, 300, 510]                       # 15%, 50%, 85% of a 600 s take
    assert all(p[4] == eye_contact_api.PREVIEW_SECONDS for p in be.previewed)
    assert len(clips) == 3 and clips[0]["before_url"].startswith("/api/eye_contact/file?path=")
    saved = Project.load(PID).metadata["eye_contact_preview"]
    assert len(saved["clips"]) == 3 and saved["clips"][1]["report"]["median_shift_px"] == 4.2
    assert saved["clips"][0]["report"]["lens_source"] == "measured"
    assert saved["clips"][0]["contact_sheet_url"].startswith("/api/eye_contact/file?path=")

    # A second preview with the same setup does not measure again.
    eye_contact_api.preview_recording(PID, be, "be_1")
    assert len(be.analysed) == 1
    # In manual mode nothing is measured at all.
    p = Project.load(PID)
    p.metadata["eye_contact"] = {"mode": "manual"}
    p.save()
    eye_contact_api.preview_recording(PID, be, "be_1")
    assert len(be.analysed) == 1


def test_the_file_route_serves_only_the_preview_cache(project, preview_dir, tmp_path):
    c = TestClient(app)
    inside = os.path.join(preview_dir, "x_before.mp4")
    with open(inside, "wb") as fh:
        fh.write(b"mp4data")
    r = c.get("/api/eye_contact/file", params={"path": inside})
    assert r.status_code == 200 and r.content == b"mp4data"
    sheet = os.path.join(preview_dir, "x_after_abc_eyes.jpg")      # a contact sheet, next to the clips
    with open(sheet, "wb") as fh:
        fh.write(b"jpg")
    r = c.get("/api/eye_contact/file", params={"path": sheet})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"no")
    assert c.get("/api/eye_contact/file", params={"path": str(outside)}).status_code == 404
    assert c.get("/api/eye_contact/file", params={"path": os.path.join(preview_dir, "missing.mp4")}).status_code == 404


def test_the_routes_run_in_the_background_and_report_state(project, preview_dir, monkeypatch):
    monkeypatch.setattr(eye_contact_api, "POLL_S", 0)
    be = FakeBuzzEdit(preview_dir)
    monkeypatch.setattr(eye_contact_api, "BuzzEditClient", lambda: be)
    import app.api.produce_api as produce_api
    monkeypatch.setattr(produce_api, "ensure_buzzedit_running", lambda **kw: {})
    c = TestClient(app)
    r = c.post(f"/api/projects/{PID}/eye_contact/analyse")
    assert r.status_code == 200 and r.json()["state"] in ("running", "done")
    import time
    for _ in range(50):
        state = c.get(f"/api/projects/{PID}/eye_contact").json()
        if (state.get("analysing") or {}).get("state") == "done":
            break
        time.sleep(0.05)
    assert state["analysis"]["report"]["measured_shift_deg"] == 9.4
    r = c.post(f"/api/projects/{PID}/eye_contact/preview")
    assert r.status_code == 200
    for _ in range(50):
        pv = c.get(f"/api/projects/{PID}/eye_contact/preview").json()
        if (pv.get("previewing") or {}).get("state") == "done":
            break
        time.sleep(0.05)
    assert len(pv["preview"]["clips"]) == 3
    # No BuzzEdit recording yet: a clear 400, not a crash.
    p = Project.load(PID)
    p.metadata.pop("buzzedit_project_id")
    p.save()
    assert c.post(f"/api/projects/{PID}/eye_contact/preview").status_code == 400
