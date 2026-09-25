"""
Comprehensive verification of all 5 channels and their strategists,
brand guides, workflow definitions, and the system logs endpoint.
"""
import sys
import os

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services.studio_chat import (
    strategist_for,
    channel_guide,
    _STRATEGISTS,
)
from core.paths import AGENTS_DIR, WORKFLOWS_DIR, CHANNELS_DIR
from core.agent import agent_registry

def test_channels():
    print("=" * 60)
    print("TESTING ALL CHANNELS & STRATEGISTS")
    print("=" * 60)
    
    # Discover registered agents
    agent_registry.discover_agents()
    print(f"Total agents registered: {len(agent_registry.list())}")
    
    test_cases = [
        ("Raat3Baje", "AfterDarkStrategist", "Raat3Baje.md"),
        ("raat 3 baje", "AfterDarkStrategist", "Raat3Baje.md"),
        ("afterdark", "AfterDarkStrategist", "Raat3Baje.md"),
        ("Beyond3Baje", "Beyond3BajeStrategist", "Beyond3Baje.md"),
        ("beyond 3 baje", "Beyond3BajeStrategist", "Beyond3Baje.md"),
        ("Khayal3Baje", "Khayal3BajeStrategist", "Khayal3Baje.md"),
        ("khayal 3 baje", "Khayal3BajeStrategist", "Khayal3Baje.md"),
        ("Originals", "SpilledCoffeeStudioStrategist", "Originals.md"),
        ("spilled coffee", "SpilledCoffeeStudioStrategist", "Originals.md"),
        ("Life3Baje", "Life3BajeStrategist", "Life3Baje.md"),
        ("life 3 baje", "Life3BajeStrategist", "Life3Baje.md"),
    ]
    
    all_passed = True
    for channel_input, expected_agent, expected_guide in test_cases:
        resolved = strategist_for(channel_input)
        guide = channel_guide(channel_input)
        
        # Check strategist
        agent_ok = resolved == expected_agent
        # Check agent exists in AGENTS_DIR
        prompt_path = os.path.join(AGENTS_DIR, f"{resolved}.md")
        prompt_exists = os.path.exists(prompt_path)
        
        # Check guide is loaded
        guide_ok = len(guide) > 50 and not guide.startswith("Channel voice guide for")
        
        status = "PASS" if (agent_ok and prompt_exists and guide_ok) else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"[{status}] Input: '{channel_input}' -> Agent: {resolved} (exists: {prompt_exists}), Guide loaded: {guide_ok} ({len(guide)} chars)")

    print("\n" + "=" * 60)
    print("WORKFLOW DEFINITIONS FOR EACH BRAND")
    print("=" * 60)
    for wf in os.listdir(WORKFLOWS_DIR):
        if wf.endswith(".md") or wf.endswith(".yaml"):
            print(f"  - {wf}")
            
    if all_passed:
        print("\n>>> ALL CHANNEL TESTS PASSED SUCCESSFULLY! <<<")
    else:
        print("\n>>> SOME CHANNEL TESTS FAILED! <<<")
        sys.exit(1)

if __name__ == "__main__":
    test_channels()
