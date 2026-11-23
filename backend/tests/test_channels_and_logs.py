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
        "TheTallStoryteller": "TheTallStorytellerStrategist",
        "the tall storyteller": "TheTallStorytellerStrategist",
    }
    for ch, expected_agent in mappings.items():
        assert strategist_for(ch) == expected_agent, f"Failed resolving channel {ch}"
        agent_file = os.path.join(AGENTS_DIR, f"{expected_agent}.md")
        assert os.path.exists(agent_file), f"Agent file missing: {agent_file}"

def test_all_channel_guides_load():
    channels = ["Raat3Baje", "Beyond3Baje", "Khayal3Baje", "Originals", "Life3Baje", "TheTallStoryteller"]
    for ch in channels:
        guide = channel_guide(ch)
        assert len(guide) > 50, f"Guide too short or empty for {ch}"
        assert not guide.startswith("Channel voice guide for"), f"Fallback guide used for {ch}"


def test_the_tall_storyteller_is_fully_wired():
    """New channel (2026-10-23): guide, strategist, workflow, Shorts formats,
    voice/style defaults and the greeting all resolve, the way the other five do."""
    from core.agent import agent_registry
    from core.workflow import WorkflowRegistry
    from app.services import auto_story, shorts_desk, writing_style

    assert strategist_for("TheTallStoryteller") == "TheTallStorytellerStrategist"
    agent_registry.discover_agents()
    assert "thetallstorytellerstrategist" in agent_registry.agents

    registry = WorkflowRegistry()
    registry.discover_workflows()
    assert registry.get("thetallstoryteller_story") is not None

    assert auto_story.default_voice_for("TheTallStoryteller") == "sudhansu_story"
    assert auto_story.voice_style_for("TheTallStoryteller") == {"mood": "warm"}
    # The horror channels keep their own defaults (no regression from the new table).
    assert auto_story.default_voice_for("Raat3Baje") == "sudhansu_horror"

    formats = set(shorts_desk.FORMATS["TheTallStoryteller"])
    assert formats == {"detective", "comedy", "crime"}   # never horror (creator, 2026-10-24)
    assert "long_story" in auto_story.channel_formats("TheTallStoryteller")

    assert writing_style.greeting("TheTallStoryteller") == \
        "Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain The Tall Storyteller."

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
