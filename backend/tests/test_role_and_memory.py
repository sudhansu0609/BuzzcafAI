from unittest.mock import MagicMock, patch

from core.base_agent import BaseAgent


class _A(BaseAgent):
    pass


def _agent():
    llm = MagicMock()
    llm.generate_text.return_value = "ok"
    return _A("WriterAgent", llm), llm


def test_use_memory_false_has_no_memory_section():
    agent, llm = _agent()
    agent.use_memory = False
    with patch("memory.memory.memory_system") as ms:
        agent.execute("write")
        ms.retrieve.assert_not_called()
    assert "Persistent Agent Memory" not in llm.generate_text.call_args.kwargs["system_prompt"]


def test_role_block_in_prompt():
    agent, _ = _agent()
    assert "### Stay in your role" in agent.system_prompt
    assert "You are WriterAgent" in agent.system_prompt


def test_voice_over_is_styled_not_script():
    from runtime.workflow import SCRIPT_OUTPUT_TYPES, STYLE_OUTPUT_TYPES
    assert "voice_over" in STYLE_OUTPUT_TYPES and "voice_over" not in SCRIPT_OUTPUT_TYPES
