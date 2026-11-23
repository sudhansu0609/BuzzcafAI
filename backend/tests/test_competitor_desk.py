"""Competitor desk: outlier/days filter, analysis saved, vault row. No network."""

from datetime import datetime, timedelta, timezone

from app.services import competitor_desk as cd


def _entry(i, views, days_ago):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp()
    return {"id": f"v{i}", "title": f"t{i}", "view_count": views, "duration": 600, "timestamp": ts}


def test_outlier_and_days_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "COMPETITORS_DIR", tmp_path)
    rows = cd.rows_from_entries([_entry(1, 100, 5), _entry(2, 100, 50), _entry(3, 500, 10)], "C")
    assert {r["id"]: r["outlier"] for r in rows} == {"v1": 1.0, "v2": 1.0, "v3": 5.0}
    cd.audience_desk._write(tmp_path / "B" / "scan.json", {"fetched_at": "x", "videos": rows})
    out = cd.videos("B", days=30)["videos"]
    assert [r["id"] for r in out] == ["v3", "v1"]


def test_analysis_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "COMPETITORS_DIR", tmp_path)
    monkeypatch.setattr(cd, "video_detail", lambda vid: {"id": vid, "title": "T"})
    monkeypatch.setattr("app.services.shorts_desk._agent_json",
                        lambda agent, task: {"videos": [{"id": "a"}], "ideas": [{"title": "Ours"}]})
    res = cd.analyze("B", ["a"])
    assert res["ideas"][0]["title"] == "Ours"
    assert cd.latest_analysis("B")["video_ids"] == ["a"]


def test_save_idea_row(monkeypatch):
    seen = {}
    monkeypatch.setattr("app.services.topic_store.add_topic", lambda f, **kw: seen.update(f) or f)
    cd.save_idea("B", {"title": "Ours"}, [{"id": "a", "views": 10, "outlier": 4}])
    assert seen["source_type"] == "competitor_inspired" and seen["evidence"]["videos"][0]["id"] == "a"


def _hit(i, cid, views):
    return {"id": f"x{i}", "title": f"t{i}", "channel": cid, "channel_id": cid, "views": views}


def test_aggregate_drops_own_and_excluded():
    res = {"q1": [_hit(1, "UCa", 1000), _hit(2, "UCown", 9), _hit(3, "UCbad", 9)],
           "q2": [_hit(4, "UCa", 3000), _hit(5, "UCb", 50)]}
    out = cd.aggregate(res, {"ucown", "ucbad"})
    assert [r["channel_id"] for r in out] == ["UCa", "UCb"]
    assert out[0]["appearances"] == 2 and out[0]["median_views"] == 2000


def test_rediscovery_keeps_manual_and_exclude_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(cd.audience_desk, "AUDIENCE_DIR", tmp_path)
    monkeypatch.setattr(cd.audience_desk, "_own_channel_ids", lambda b: [])
    monkeypatch.setattr(cd, "niche_queries", lambda b: ["q"])
    monkeypatch.setattr(cd, "search_both_ways", lambda q, limit=30: [_hit(1, "UCa", 900), _hit(2, "UCb", 800)])
    monkeypatch.setattr(cd, "_relevant", lambda b, c: {x["channel_id"]: "same niche" for x in c})
    cd.audience_desk.set_sources("B", {"competitors": [{"url": "https://www.youtube.com/@mine"}]})
    cd.discover("B")
    rows = cd.audience_desk.sources("B")["competitors"]
    assert {r["source"] for r in rows} == {"manual", "auto"} and any(r.get("reason") for r in rows)
    cd.exclude("B", "UCa")
    cd.discover("B")
    src = cd.audience_desk.sources("B")
    assert "uca" in src["excluded"] and all(r.get("channel_id") != "UCa" for r in src["competitors"])
    assert any(r["url"].endswith("@mine") for r in src["competitors"])


def test_run_all_rediscovers_stale_only_and_continues(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "COMPETITORS_DIR", tmp_path)
    monkeypatch.setattr(cd.audience_desk, "AUDIENCE_DIR", tmp_path / "aud")
    monkeypatch.setattr("app.services.master_control.wait_if_paused", lambda *a, **k: False)
    cd.set_settings({"brands": ["Fresh", "Old", "Boom"], "rediscover_days": 7})
    fresh = {"url": "u", "source": "auto"}
    for b in ("Fresh", "Old", "Boom"):
        cd.audience_desk.set_sources(b, {"competitors": [fresh]})
    cd.audience_desk._write(cd._brand_dir("Fresh") / "discovered.json", {"last_discovered": datetime.now().isoformat()})
    cd.audience_desk._write(cd._brand_dir("Old") / "discovered.json",
                            {"last_discovered": (datetime.now() - timedelta(days=9)).isoformat()})
    cd.audience_desk._write(cd._brand_dir("Boom") / "discovered.json", {"last_discovered": datetime.now().isoformat()})
    found, scanned = [], []
    monkeypatch.setattr(cd, "discover", lambda b, **kw: found.append(b) or [])
    def fake_scan(b, **kw):
        if b == "Fresh":
            raise RuntimeError("down")
        scanned.append(b)
    monkeypatch.setattr(cd, "scan", fake_scan)
    rec = cd.run_all()
    assert found == ["Old"] and scanned == ["Old", "Boom"]
    assert rec["done"] == ["Old", "Boom"] and rec["failed"][0]["brand"] == "Fresh"
    assert cd.settings()["last_run"]
