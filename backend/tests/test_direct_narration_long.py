"""A script too long to direct is narrated raw without loading a model (2026-10-26)."""
from app.services import auto_story


def test_long_script_skips_the_model(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("NarrationDirector must not be called for a long script")

    monkeypatch.setattr("app.services.shorts_desk._agent_json", boom)
    text = "Raat ke do baje hain. " * 1000
    assert auto_story.direct_narration(text, "Beyond3Baje") == text
