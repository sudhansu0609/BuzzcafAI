"""The research step as a tool loop (runtime/research_loop.py): the
researcher searches before it writes, its lookups are run and fed back, a
dossier from memory is sent back once, and the engine's single-call path is
the fallback when no model answers the chat."""

import json

import pytest

from runtime import research_loop as rl

DOSSIER = {"timeline": ["1999 - a patrol goes missing (https://x/1)"],
           "facts": ["[Folklore] a voice that calls by name (https://x/2)"],
           "sources": ["Forest lore - https://x/2"],
           "story_material": {"world": ["the chowki register"], "twists": ["the note was his own"]}}


class ChatLLM:
    """Replies per turn; records the messages it was given."""

    def __init__(self, replies, simulated=False):
        self.replies = list(replies)
        self.seen = []
        self.simulated = simulated
        self.last_response_simulated = False

    def generate_chat(self, system_prompt, messages, require_json=False, tier=None, temperature=None):
        self.seen.append([dict(m) for m in messages])
        self.last_response_simulated = self.simulated
        return self.replies.pop(0) if self.replies else json.dumps(DOSSIER)

    def generate_text(self, system_prompt, user_prompt, require_json=False, tier=None, temperature=None):
        self.last_response_simulated = self.simulated
        return "single call"


class Agent:
    def __init__(self, llm):
        self.llm_service = llm
        self.system_prompt = "researcher"
        self.model_tier = "strong"
        self.temperature = 0.3
        self.executed = []

    def refresh_prompt(self):
        pass

    def execute(self, task, require_json=False):
        self.executed.append(task)
        return self.llm_service.generate_text("", task, require_json)


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    """Tool tags resolve locally: no network."""
    from app.services import studio_chat as sc
    monkeypatch.setattr(sc, "process_web_research_tags", lambda text: f"RESULT for {text.strip()}")


def test_searches_are_run_and_fed_back_before_the_dossier():
    llm = ChatLLM(["[WEB_SEARCH: forest guard night patrol India]\n[WEB_SEARCH: Pishach voice folklore]\n"
                   "[WEB_FETCH: https://x/2]",
                   "```json\n" + json.dumps(DOSSIER) + "\n```"])
    logs = []
    out = rl.run(Agent(llm), "TASK", logs.append)
    assert out["dossier"]["timeline"] == DOSSIER["timeline"] and out["turns"] == 2
    assert [c.split(":")[0] for c in out["calls"]] == ["web search", "web search", "fetch"]
    # The first prompt carries the tool guide; the second turn carries the results.
    assert "Search FIRST" in llm.seen[0][0]["content"]
    second = llm.seen[1]
    assert second[1]["role"] == "assistant" and "RESULT for [WEB_FETCH: https://x/2]" in second[2]["content"]
    assert any("3 tool call(s)" in m for m in logs)
    assert json.loads(out["raw"])["story_material"]["twists"] == ["the note was his own"]


def test_a_dossier_from_memory_is_sent_back_to_search_first():
    llm = ChatLLM([json.dumps(DOSSIER), "[WEB_SEARCH: something]", json.dumps(DOSSIER)])
    logs = []
    out = rl.run(Agent(llm), "TASK", logs.append)
    assert out["turns"] == 3 and out["calls"] == ["web search: something"]
    assert "memory is not research" in llm.seen[1][-1]["content"]
    assert any("without a single search" in m for m in logs)


def test_the_last_chance_turn_forces_the_dossier():
    # Two turns of searching, then the last-chance turn: told to stop and write.
    llm = ChatLLM(["[WEB_SEARCH: q]", "[WEB_SEARCH: q2]", json.dumps(DOSSIER)])
    out = rl.run(Agent(llm), "TASK", lambda m: None, max_turns=2)
    assert out["turns"] == 3 and len(out["calls"]) == 2
    assert "Stop researching now" in llm.seen[2][-1]["content"]
    # A model that keeps searching past the last chance delivers no dossier.
    llm = ChatLLM(["[WEB_SEARCH: q]"] * 10)
    out = rl.run(Agent(llm), "TASK", lambda m: None, max_turns=2)
    assert out["dossier"] is None and out["calls"] == ["web search: q"] * 2


def test_prose_to_the_end_is_kept_verbatim_and_an_empty_reply_fails():
    logs = []
    out = rl.run(Agent(ChatLLM(["just prose"] * 10)), "TASK", logs.append, max_turns=2)
    assert out["dossier"] is None and out["raw"] == "just prose" and out["turns"] == 3
    assert any("kept as prose" in m for m in logs)
    with pytest.raises(RuntimeError):
        rl.run(Agent(ChatLLM(["   "])), "TASK", lambda m: None, max_turns=2)


def test_no_model_falls_back_to_the_single_call_and_says_so():
    llm = ChatLLM([json.dumps(DOSSIER)], simulated=True)
    agent = Agent(llm)
    out = rl.run(agent, "TASK", lambda m: None)
    assert agent.executed == ["TASK"] and out["simulated"] and out["raw"] == "single call" and out["dossier"] is None


def test_a_service_without_chat_uses_the_single_call():
    class TextOnly:
        last_response_simulated = False

        def generate_text(self, system_prompt, user_prompt, require_json=False, tier=None, temperature=None):
            return json.dumps(DOSSIER)

    out = rl.run(Agent(TextOnly()), "TASK", lambda m: None)
    assert out["dossier"]["facts"] == DOSSIER["facts"] and out["calls"] == []


def test_the_engine_writes_the_story_material_section(monkeypatch, tmp_path):
    from runtime import workflow as wf
    assert "story_material" in wf.RESEARCH_SECTIONS
    rendered = wf._render_section(DOSSIER["story_material"])
    assert "### World" in rendered and "- the chowki register" in rendered and "### Twists" in rendered
    assert "story_material" in wf.RESEARCH_JSON_INSTRUCTION and "[Verified]" in wf.RESEARCH_JSON_INSTRUCTION
