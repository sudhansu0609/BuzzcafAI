"""Tests for Strict Local LLM Mode, Ollama Integration, and Privacy-Preserving Web Research."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from integrations.llm import LLMService, LOCAL_PROVIDERS, LOCAL_FALLBACK_ORDER
from app.services.web_research import (
    sanitize_search_query,
    search_wikipedia,
    search_duckduckgo_instant,
    search_searxng,
    search_web,
    fetch_page_content,
    build_research_brief,
    web_research_service,
)
from app.services.studio_chat import process_web_research_tags


@pytest.fixture
def client():
    return TestClient(app)


# ───────────────────────── Part 1: Local Privacy & Routing ─────────────────────────

def test_local_only_strictly_blocks_cloud_providers():
    """Verify that when local_only is True, cloud providers (gemini, openai) are never in provider order."""
    service = LLMService()
    service.config["local_only"] = True
    service.config["selected_provider"] = "lm_studio"
    service.config["gemini_api_key"] = "test-gemini-key"
    service.config["openai_api_key"] = "test-openai-key"

    order = service._provider_order()
    for provider in order:
        assert provider in LOCAL_PROVIDERS, f"Provider '{provider}' is not local but appeared in local_only order: {order}"
    assert "gemini" not in order
    assert "openai" not in order


def test_local_providers_include_ollama():
    """Verify that Ollama is registered as a first-class local provider."""
    assert "ollama" in LOCAL_PROVIDERS
    assert "ollama" in LOCAL_FALLBACK_ORDER

    service = LLMService()
    service.config["ollama_url"] = "http://localhost:11434/v1"
    service.config["ollama_model"] = "qwen3.5:9b"
    assert service._local_url("ollama") == "http://localhost:11434/v1"
    assert service._model_for("ollama", tier=None) == "qwen3.5:9b"


def test_local_only_blocks_remote_calls(monkeypatch):
    """Ensure no HTTP request is made to Google or OpenAI when local_only is True."""
    service = LLMService()
    service.config["local_only"] = True
    service.config["gemini_api_key"] = "fake-key"
    service.config["openai_api_key"] = "fake-key"

    def mock_post(url, *args, **kwargs):
        if "googleapis.com" in url or "openai.com" in url:
            pytest.fail(f"Privacy breach: request made to external cloud endpoint: {url}")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": [{"message": {"content": "Local response"}}]}
        return mock_resp

    monkeypatch.setattr("requests.post", mock_post)

    # Calling generate_text in local mode should only try local endpoints
    result = service.generate_text("System", "User prompt")
    assert result == "Local response"


# ───────────────────────── Part 2: Query Sanitization ─────────────────────────

def test_query_sanitizer_removes_file_paths_and_secrets():
    # Windows path
    dirty_win = "Search history C:\\Users\\User\\secret_project\\notes.txt Bhangarh Fort"
    cleaned_win = sanitize_search_query(dirty_win)
    assert "C:\\" not in cleaned_win
    assert "notes.txt" not in cleaned_win
    assert "Bhangarh Fort" in cleaned_win

    # Unix path
    dirty_unix = "Research /home/user/workspace/keys.env Indus Valley"
    cleaned_unix = sanitize_search_query(dirty_unix)
    assert "/home/" not in cleaned_unix
    assert "Indus Valley" in cleaned_unix

    # API Keys
    dirty_key = "sk-1234567890abcdef1234567890abcdef Mayan calendar"
    cleaned_key = sanitize_search_query(dirty_key)
    assert "sk-" not in cleaned_key
    assert "Mayan calendar" in cleaned_key

    # Tags
    dirty_tags = "[WEB_SEARCH: Voynich manuscript] [INVOKE_AGENT: ResearchAgent]"
    cleaned_tags = sanitize_search_query(dirty_tags)
    assert "INVOKE_AGENT" not in cleaned_tags
    assert "Voynich manuscript" in cleaned_tags


# ───────────────────────── Part 3: HTML Parsing & Search ─────────────────────────

def test_fetch_page_content_strips_scripts_and_styles(monkeypatch):
    html_sample = """
    <html>
        <head><style>.ad { color: red; }</style></head>
        <body>
            <nav><a href="#">Menu</a></nav>
            <script>alert("tracker");</script>
            <h1>The Lost City</h1>
            <p>Archaeologists have uncovered an ancient settlement dating back 3,000 years.</p>
            <footer>Copyright 2026</footer>
        </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html_sample

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: mock_resp)

    text = fetch_page_content("https://example.com/article")
    assert "tracker" not in text
    assert "color: red" not in text
    assert "The Lost City" in text
    assert "ancient settlement" in text


def test_search_web_aggregates_and_deduplicates():
    res = search_web("Bhangarh Fort", max_results=3)
    assert isinstance(res, list)
    if res:
        first = res[0]
        assert "title" in first
        assert "snippet" in first
        assert "url" in first


def test_searxng_integration(monkeypatch):
    """Test SearXNG response handling."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {
                "title": "SearXNG Top Result",
                "content": "Verified content from SearXNG metasearch",
                "url": "https://searxng.local/article1",
                "engine": "google"
            }
        ]
    }
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: mock_resp)

    results = search_searxng("test query", base_url="http://localhost:8080", max_results=2)
    assert len(results) == 1
    assert results[0]["title"] == "SearXNG Top Result"
    assert "SearXNG (google)" in results[0]["source"]


def test_tag_resolution_in_chat():
    sample_text = "Here is what I found: [WEB_SEARCH: Bhangarh Fort] Please proceed with the outline."
    resolved = process_web_research_tags(sample_text)
    assert "[WEB_SEARCH:" not in resolved
    assert "Verified Web Research" in resolved


# ───────────────────────── Part 4: API Endpoints ─────────────────────────

def test_local_models_endpoint(client):
    resp = client.get("/api/settings/local-models")
    assert resp.status_code == 200
    data = resp.json()
    assert "lm_studio" in data
    assert "ollama" in data
    assert "llamacpp" in data
    assert isinstance(data["lm_studio"], list)
    assert isinstance(data["ollama"], list)
    assert isinstance(data["llamacpp"], list)


def test_research_search_endpoint(client):
    resp = client.get("/api/research/search?q=Bhangarh+Fort&limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert data["query"] == "Bhangarh Fort"


def test_searxng_test_endpoint(client, monkeypatch):
    """Test SearXNG probe endpoint when SearXNG succeeds and fails."""
    # 1. Success case
    with patch("app.services.web_research.search_searxng") as mock_sx:
        mock_sx.return_value = [{"title": "Result", "snippet": "Text", "url": "http://example.com"}]
        resp = client.get("/api/research/searxng-test?url=http://localhost:8080")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "Successfully connected" in data["message"]

    # 2. Unreachable case
    with patch("app.services.web_research.search_searxng", side_effect=Exception("Connection refused")):
        resp = client.get("/api/research/searxng-test?url=http://invalid.host:9999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "Could not reach" in data["message"]

