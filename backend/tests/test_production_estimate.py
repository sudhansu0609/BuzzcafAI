"""Clip / time estimate shown under the Video / Images sliders."""
from integrations import production_estimate as pe

SPEEDS = {"still_s": 20.0, "clip_s": 200.0, "render_factor": 0.7, "fixed_s": 600}


def test_the_basement_mix_matches_what_the_planner_made():
    # 807.7 s at 20% video / 10% images was planned as 32 clips and 20 stills.
    e = pe.estimate(807.67, 0.2, 0.1, SPEEDS)
    assert (e["clips"], e["stills"]) == (32, 20)


def test_every_clip_also_needs_its_starting_still():
    e = pe.estimate(600, 0.5, 0.0, SPEEDS)          # 300 s of clips = 60 clips
    assert e["clips"] == 60 and e["pictures_s"] == 60 * 20 and e["clips_s"] == 60 * 200
    assert e["total_s"] == 60 * 20 + 60 * 200 + 420 + 600


def test_speeds_are_read_from_a_render_report():
    report = {"timings": [{"stage": "assets", "seconds": 3807.8}, {"stage": "render", "seconds": 574.9}],
              "generation": {"video_phase": {"made": 13}}, "assets_generated": 52,
              "program": {"duration_s": 807.67}}
    found = pe._report_speeds(report)
    assert 200 < found["clip_s"] < 215 and found["render_factor"] == 0.71


def test_a_run_without_clips_teaches_nothing():
    assert pe._report_speeds({"timings": [{"stage": "assets", "seconds": 500}],
                              "generation": {"video_phase": {"made": 0}}}) is None


def test_runtime_falls_back_to_the_script(tmp_path):
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "draft.md").write_text("raat " * 300 + "[broll: ignored words here]", encoding="utf-8")

    class _P:
        metadata = {}
        assets = {"script": "script/draft.md"}

        def get_project_dir(self):
            return str(tmp_path)
    rt = pe.runtime_for(_P())
    assert rt["seconds"] == 120.0 and "300 words" in rt["source"]
