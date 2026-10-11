"""
produce_video's model routing and stock-footage plumbing
(`app/api/produce_api.py`): Settings -> "Use Claude for video production"
sends the Studio's own planning calls to the Claude proxy and tells BuzzEdit
to run its passes there too; Settings -> "Use Pixabay stock footage" hands
the key to BuzzEdit before a render that may fall back to stock.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import app

CLAUDE_ON = {
    "produce_llm_provider": "claude", "claude_api_key": "sk-local-x",
    "claude_url": "http://127.0.0.1:8787/v1", "claude_model": "sonnet",
}


@pytest.fixture
def client():
    return TestClient(app)


def _config(monkeypatch, **cfg):
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: dict(cfg))


def test_production_is_routed_to_claude_only_with_the_switch_and_a_key(monkeypatch):
    _config(monkeypatch, **CLAUDE_ON)
    assert produce_api.produce_llm_provider() == "claude"
    assert produce_api.produce_llm_service().forced_provider == "claude"

    _config(monkeypatch, **dict(CLAUDE_ON, produce_llm_provider="auto"))
    assert produce_api.produce_llm_provider() is None

    _config(monkeypatch, **dict(CLAUDE_ON, claude_api_key=""))
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    assert produce_api.produce_llm_provider() is None
    assert produce_api.produce_llm_service().forced_provider is None


def test_buzzedit_gets_the_remote_model_fields_only_when_routed(monkeypatch):
    _config(monkeypatch, **CLAUDE_ON)
    assert produce_api.buzzedit_llm_settings() == {
        "llm_provider": "openai_compat", "llm_base_url": "http://127.0.0.1:8787/v1",
        "llm_api_key": "sk-local-x", "llm_model": "sonnet",
    }
    _config(monkeypatch, **dict(CLAUDE_ON, produce_llm_provider="auto"))
    assert produce_api.buzzedit_llm_settings() == {}


def test_stock_key_sync_is_skipped_without_a_key_and_survives_buzzedit_being_down(monkeypatch):
    _config(monkeypatch, pixabay_enabled=True, pixabay_api_key="")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    assert produce_api.sync_stock_keys_to_buzzedit() is None

    _config(monkeypatch, pixabay_enabled=True, pixabay_api_key="pix-key")

    def down(self, **kwargs):
        raise produce_api.BuzzEditUnavailable("not running")

    monkeypatch.setattr(produce_api.BuzzEditClient, "set_stock_keys", down)
    assert produce_api.sync_stock_keys_to_buzzedit() is None

    sent = {}

    def up(self, pexels_api_key=None, pixabay_api_key=None):
        sent["pixabay"] = pixabay_api_key
        return {"pixabay_api_key_set": True}

    monkeypatch.setattr(produce_api.BuzzEditClient, "set_stock_keys", up)
    assert produce_api.sync_stock_keys_to_buzzedit() == {"pixabay_api_key_set": True}
    assert sent["pixabay"] == "pix-key"


def test_claude_status_endpoint_reports_the_probe_and_the_routing(client, monkeypatch):
    _config(monkeypatch, **CLAUDE_ON)
    monkeypatch.setattr(produce_api, "probe_claude", lambda: {
        "url": "http://127.0.0.1:8787/v1", "model": "sonnet", "key_set": True,
        "online": True, "authorized": True, "models": ["sonnet"], "message": "ok",
    })
    body = client.get("/api/produce/claude/status").json()
    assert body["authorized"] is True
    assert body["routed"] is True


def test_stock_status_endpoint_tolerates_buzzedit_offline(client, monkeypatch):
    _config(monkeypatch, pixabay_enabled=True, pixabay_api_key="pix-key")

    def down(self):
        raise produce_api.BuzzEditUnavailable("not running")

    monkeypatch.setattr(produce_api.BuzzEditClient, "get_stock_keys", down)
    body = client.get("/api/produce/stock/status").json()
    assert body == {"pixabay_enabled": True, "pixabay_key_set": True, "buzzedit": None}


def test_stock_sync_endpoint_needs_a_key(client, monkeypatch):
    _config(monkeypatch, pixabay_enabled=True, pixabay_api_key="")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    assert client.post("/api/produce/stock/sync").status_code == 400


def test_settings_api_masks_the_new_keys_and_keeps_them_on_a_blank_resave(client, tmp_path, monkeypatch):
    import integrations.llm as llm_module
    monkeypatch.setattr(llm_module, "CONFIG_PATH", str(tmp_path / "config.json"))
    # Saving a Pixabay key pushes it to BuzzEdit on a background thread --
    # never let a test hand a fake key to a real BuzzEdit that happens to be up.
    pushed = []
    monkeypatch.setattr(produce_api, "sync_stock_keys_to_buzzedit", lambda client=None: pushed.append(1))

    res = client.post("/api/settings", json={
        "claude_api_key": "sk-local-x", "claude_model": "haiku", "produce_llm_provider": "claude",
        "pixabay_api_key": "pix-key", "pixabay_enabled": True,
    })
    assert res.status_code == 200, res.text
    shown = client.get("/api/settings").json()
    assert shown["claude_api_key"] == "********" and shown["claude_api_key_set"] is True
    assert shown["pixabay_api_key"] == "********" and shown["pixabay_api_key_set"] is True
    assert shown["claude_model"] == "haiku"
    assert shown["produce_llm_provider"] == "claude"
    assert shown["pixabay_enabled"] is True

    # Re-saving the masked value must not overwrite the stored key.
    client.post("/api/settings", json={"claude_api_key": "********", "pixabay_api_key": ""})
    stored = llm_module.load_config()
    assert stored["claude_api_key"] == "sk-local-x"
    assert stored["pixabay_api_key"] == "pix-key"
    import time
    time.sleep(0.05)  # the push runs on a daemon thread
    assert pushed  # the (stubbed) BuzzEdit sync was triggered by the key save
