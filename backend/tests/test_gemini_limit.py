from datetime import datetime, timedelta

from integrations import gemini_limit


def test_record_active_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_limit, "LIMIT_FILE", str(tmp_path / "lim.json"))
    assert gemini_limit.active() is None
    future = (datetime.now().astimezone() + timedelta(minutes=5)).isoformat()
    gemini_limit.record(future, True, "x")
    assert gemini_limit.active()["estimated"] is True
    gemini_limit.clear()
    assert gemini_limit.active() is None
    gemini_limit.record((datetime.now().astimezone() - timedelta(minutes=1)).isoformat(), False, "old")
    assert gemini_limit.active() is None
