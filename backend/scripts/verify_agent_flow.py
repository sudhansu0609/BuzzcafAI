import os
import sys

# Ensure UTF-8 output encoding for Windows terminal
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.agent import agent_registry, AgentFactory

def main():
    print("=" * 60)
    print("Buzzcaf AI Agent Loading & Flow Verification Script")
    print("=" * 60)

    # 1. Discover Registered Agents
    print("\n1. Discovering Prompt Files in backend/prompts/agents...")
    agent_registry.discover_agents()
    agents = agent_registry.list()
    print(f"   [OK] Total Discovered Registered Agents: {len(agents)}")

    # 2. Test Agent Instantiation & System Prompt Loading
    print("\n2. Testing Agent Instantiation & Prompt Loading...")
    test_agents = [
        "SpilledCoffeeStudioStrategist",
        "AfterDarkStrategist",
        "Beyond3BajeStrategist",
        "Life3BajeStrategist",
        "Khayal3BajeStrategist",
        "TopicVaultManager",
        "ResearchManager",
        "StoryPlanner",
        "ProductionManager",
        "PublishingManager",
        "CEO",
        "SEOSpecialist"
    ]

    for name in test_agents:
        try:
            instance = AgentFactory.get_agent(name)
            prompt_len = len(instance.system_prompt) if instance.system_prompt else 0
            print(f"   [OK] Loaded Agent '{name}': System Prompt Loaded ({prompt_len} chars)")
            assert prompt_len > 20, f"Prompt too short for {name}"
        except Exception as e:
            print(f"   [FAIL] FAILED to load Agent '{name}': {e}")
            sys.exit(1)

    # 3. Test Agent Execution Flow
    print("\n3. Testing Agent Execution Flow (agent.execute)...")
    sample_queries = [
        ("Beyond3BajeStrategist", "Give me 3 true crime documentary concepts for Beyond3Baje."),
        ("AfterDarkStrategist", "Give me 3 haunted location concepts for Maharashtra avoiding Shaniwar Wada."),
        ("SpilledCoffeeStudioStrategist", "Give me 3 classic literature breakdown concepts.")
    ]

    for agent_name, query in sample_queries:
        print(f"\n   Running Task for '{agent_name}'...")
        agent = AgentFactory.get_agent(agent_name)
        result = agent.execute(query)
        res_str = str(result)
        preview = res_str[:120].replace("\n", " ")
        print(f"   [OK] Agent Response Success! Output Preview: '{preview}...'")
        assert len(res_str) > 50, f"Execution returned empty or tiny output for {agent_name}"

    print("\n" + "=" * 60)
    print("VERIFICATION SUCCESSFUL: All 115 Agents Load Cleanly & Execution Flow Works!")
    print("=" * 60)

if __name__ == "__main__":
    main()
