import pytest
from integrations.llm import (
    normalize_model_name,
    models_match,
    is_model_already_loaded,
    get_loaded_lm_studio_models,
    ensure_local_model_loaded,
    LLMService,
)
from app.services.studio_chat import process_studio_tools_tags
from starlette.testclient import TestClient
from app.main import app

def test_model_name_normalization_and_matching():
    # HuggingFace path vs LMS local identifier
    assert normalize_model_name("ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF") == "qwen3827bgsqrco"
    assert normalize_model_name("qwen3.8-27b-gsq-rco") == "qwen3827bgsqrco"
    assert models_match("ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF", "qwen3.8-27b-gsq-rco")
    assert models_match("HauhauCS/Gemma4-12B-QAT-Uncensored-GGUF", "gemma4-12b-qat-uncensored-hauhaucs-balanced")

def test_is_model_already_loaded_logic():
    loaded_pool = [
        "gemma4-12b-qat-uncensored-hauhaucs-balanced",
        "qwen3.8-27b-gsq-rco",
    ]
    # Exact match
    is_loaded, mid = is_model_already_loaded("qwen3.8-27b-gsq-rco", loaded_pool)
    assert is_loaded is True
    assert mid == "qwen3.8-27b-gsq-rco"

    # HuggingFace path fuzzy match
    is_loaded, mid = is_model_already_loaded("ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF", loaded_pool)
    assert is_loaded is True
    assert mid == "qwen3.8-27b-gsq-rco"

    # Default / empty model
    is_loaded, mid = is_model_already_loaded("", loaded_pool)
    assert is_loaded is True
    assert mid == loaded_pool[0]

    # Non-loaded model
    is_loaded, mid = is_model_already_loaded("llama-3-8b-instruct", loaded_pool)
    assert is_loaded is False
    assert mid is None

def test_ensure_local_model_loaded_skips_when_already_loaded():
    # Calling ensure_local_model_loaded for an active local model should return already_loaded: True
    loaded = get_loaded_lm_studio_models("http://localhost:1234")
    if loaded:
        res = ensure_local_model_loaded("lm_studio", loaded[0])
        assert res.get("loaded") is True
        assert res.get("already_loaded") is True

def test_process_studio_tools_tags():
    raw_text = (
        "Let me check the status.\n"
        "[MODEL_STATUS]\n"
        "[NAVIGATE_TAB: projects]\n"
        "[CREATE_PROJECT: AI Agents in 2026]\n"
        "All done!"
    )
    cleaned = process_studio_tools_tags(raw_text, "Buzzcaf Media")
    assert "[MODEL_STATUS]" not in cleaned
    assert "[NAVIGATE_TAB:" not in cleaned
    assert "[CREATE_PROJECT:" not in cleaned
    assert "All done!" in cleaned
    assert "Navigate Tab: Projects" in cleaned
    assert "Active AI Engine Status" in cleaned

def test_health_endpoint_returns_model_status():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "model_status" in data
    assert "connected" in data["model_status"]
    assert "loaded" in data["model_status"]

def test_settings_reset_endpoint():
    client = TestClient(app)
    response = client.post("/api/settings/reset")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "config" in data
    assert "selected_provider" in data["config"]
    assert data["config"]["selected_provider"] == "lm_studio"
