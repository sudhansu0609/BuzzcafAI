import unittest
from unittest.mock import patch, MagicMock
from integrations.llm import LLMService

class TestLLMSelection(unittest.TestCase):
    @patch("integrations.llm.requests.post")
    def test_selected_provider_openai(self, mock_post):
        # Mock successful response from OpenAI
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from OpenAI"}}]
        }
        mock_post.return_value = mock_response

        service = LLMService()
        service.reload_config = MagicMock()
        service.config = {
            "openai_api_key": "mock_openai_key",
            "openai_model": "gpt-4o-mini",
            "selected_provider": "openai"
        }

        res = service.generate_text("System", "User")
        self.assertEqual(res, "Hello from OpenAI")
        
        # Verify OpenAI URL was called
        call_args = mock_post.call_args
        self.assertIn("api.openai.com", call_args[0][0])

    @patch("integrations.llm.requests.post")
    def test_selected_provider_gemini(self, mock_post):
        # Mock successful response from Gemini
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}}]
        }
        mock_post.return_value = mock_response

        service = LLMService()
        service.reload_config = MagicMock()
        service.config = {
            "gemini_api_key": "mock_gemini_key",
            "gemini_model": "gemini-1.5-flash",
            "selected_provider": "gemini"
        }

        res = service.generate_text("System", "User")
        self.assertEqual(res, "Hello from Gemini")
        
        # Verify Gemini URL was called
        call_args = mock_post.call_args
        self.assertIn("generativelanguage.googleapis.com", call_args[0][0])

    @patch("integrations.llm.requests.post")
    def test_selected_provider_lm_studio(self, mock_post):
        # Mock successful response from LM Studio
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from LM Studio"}}]
        }
        mock_post.return_value = mock_response

        service = LLMService()
        service.reload_config = MagicMock()
        service.config = {
            "lm_studio_url": "http://localhost:1234/v1",
            "lm_studio_model": "llama3",
            "selected_provider": "lm_studio"
        }

        res = service.generate_text("System", "User")
        self.assertEqual(res, "Hello from LM Studio")
        
        # Verify LM Studio URL was called
        call_args = mock_post.call_args
        self.assertIn("localhost:1234", call_args[0][0])
