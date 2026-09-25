"""
Unit tests for channel strategist resolution, channel guide loading,
and the system logs endpoint.
"""
import pytest
from app.services.studio_chat import strategist_for, channel_guide, _STRATEGISTS
from app.main import get_system_logs, clear_system_logs
from core.paths import AGENTS_DIR, WORKFLOWS_DIR, CHANNELS_DIR
import os

def test_all_five_channels_resolve_strategists():
    mappings = {
        "Raat3Baje": "AfterDarkStrategist",
        "raat 3 baje": "AfterDarkStrategist",
        "afterdark": "AfterDarkStrategist",
        "Beyond3Baje": "Beyond3BajeStrategist",
        "beyond 3 baje": "Beyond3BajeStrategist",
        "Khayal3Baje": "Khayal3BajeStrategist",
        "khayal 3 baje": "Khayal3BajeStrategist",
        "Originals": "SpilledCoffeeStudioStrategist",
        "spilled coffee": "SpilledCoffeeStudioStrategist",
        "Life3Baje": "Life3BajeStrategist",
        "life 3 baje": "Life3BajeStrategist",
    }
    for ch, expected_agent in mappings.items():
        assert strategist_for(ch) == expected_agent, f"Failed resolving channel {ch}"
        agent_file = os.path.join(AGENTS_DIR, f"{expected_agent}.md")
        assert os.path.exists(agent_file), f"Agent file missing: {agent_file}"

def test_all_channel_guides_load():
    channels = ["Raat3Baje", "Beyond3Baje", "Khayal3Baje", "Originals", "Life3Baje"]
    for ch in channels:
        guide = channel_guide(ch)
        assert len(guide) > 50, f"Guide too short or empty for {ch}"
        assert not guide.startswith("Channel voice guide for"), f"Fallback guide used for {ch}"

def test_get_system_logs_endpoint():
    res = get_system_logs(level="ALL", limit=50)
    assert res["status"] == "ok"
    assert "total_parsed" in res
    assert "error_count" in res
    assert "warning_count" in res
    assert isinstance(res["logs"], list)
    
    if res["logs"]:
        first = res["logs"][0]
        assert "timestamp" in first
        assert "level" in first
        assert "logger" in first
        assert "message" in first
        assert "traceback" in first
