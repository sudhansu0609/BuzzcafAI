import pytest

from app.services import director_knowledge as dk
from app.services import studio_director


def test_read_doc_rejects_outside_allowlist():
    for bad in ("../backend/config/config.json", ".env", "backend/core/agent.py"):
        with pytest.raises(ValueError):
            dk.read_doc(bad)


def test_scrub_masks_keys():
    out = dk._scrub("a sk-abc123 b AIzaSyXYZ c")
    assert "sk-abc123" not in out and "AIzaSyXYZ" not in out and "[REDACTED]" in out


def test_bogus_provider_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(studio_director, "_settings_path", lambda: str(tmp_path / "s.json"))
    with pytest.raises(ValueError):
        studio_director.set_settings({"provider": "bogus"})


def test_settings_summary_has_no_secret_keys():
    def walk(d):
        for k, v in d.items():
            yield k
            if isinstance(v, dict):
                yield from walk(v)
    for k in walk(dk.settings_summary()):
        assert not (any(w in k.lower() for w in ("api_key", "secret", "token", "password")) and not k.endswith("_set"))
