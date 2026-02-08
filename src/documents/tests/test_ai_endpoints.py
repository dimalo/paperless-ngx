from unittest.mock import MagicMock
from unittest.mock import patch

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase


class TestLLMProxyView(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser")
        self.client.force_authenticate(user=self.user)

    def test_list_models_openai(self):
        """Test listing models for OpenAI backend."""
        response = self.client.get("/api/llm_proxy/", {"backend": "openai"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Check if response contains gpt-4
        self.assertTrue(any(m["id"] == "gpt-4" for m in response.data))

    @patch("paperless.views.litellm")
    def test_connection_test_success(self, mock_litellm):
        """Test successful connection test."""
        mock_response = MagicMock()
        mock_litellm.completion.return_value = mock_response

        data = {
            "backend": "openai",
            "model": "gpt-3.5-turbo",
            "api_key": "sk-test",
        }

        response = self.client.post("/api/llm_proxy/test", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("latency_ms", response.data)
        self.assertEqual(response.data["model_info"]["model"], "openai/gpt-3.5-turbo")

        mock_litellm.completion.assert_called_once()

    @patch("paperless.views.litellm")
    def test_connection_test_failure(self, mock_litellm):
        """Test failed connection test."""
        mock_litellm.completion.side_effect = Exception("API Error")

        data = {
            "backend": "openai",
            "model": "gpt-3.5-turbo",
        }

        response = self.client.post("/api/llm_proxy/test", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"], "API Error")

    @patch("paperless.views.requests")
    def test_ollama_proxy_inheritance(self, mock_requests):
        """Test that OllamaProxyView still works and inherits correctly."""
        # Mock requests.get for Ollama tags
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": []}
        mock_requests.get.return_value = mock_response

        # Use the ollama_proxy endpoint
        response = self.client.get(
            "/api/ollama_proxy/api/tags",
            {"endpoint": "http://localhost:11434"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify call to requests.get
        # The params passed to requests.get include the request.GET params
        mock_requests.get.assert_called_once()
        args, _kwargs = mock_requests.get.call_args
        self.assertEqual(args[0], "http://localhost:11434/api/tags")

    @patch("paperless.views.requests")
    def test_list_models_ollama(self, mock_requests):
        """Test listing models for Ollama backend via LLMProxyView."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "llama3:latest"}]}
        mock_requests.get.return_value = mock_response

        # Call with backend=ollama and endpoint
        response = self.client.get(
            "/api/llm_proxy/",
            {"backend": "ollama", "endpoint": "http://localhost:11434"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["models"][0]["name"], "llama3:latest")

        # Verify it hit /api/tags
        mock_requests.get.assert_called_with(
            "http://localhost:11434/api/tags",
            timeout=5,
        )

    @patch("paperless.views.requests")
    @patch("paperless.views.litellm")
    def test_connection_test_ollama_fast_path(self, mock_litellm, mock_requests):
        """Test connection test uses fast path for Ollama."""
        # Mock version check success
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "0.1.30"}
        mock_requests.get.return_value = mock_response

        data = {
            "backend": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3",
        }

        response = self.client.post("/api/llm_proxy/test", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["model_info"]["version"], "0.1.30")

        # Verify it hit /api/version
        mock_requests.get.assert_called_with(
            "http://localhost:11434/api/version",
            timeout=5,
        )
        # Verify litellm was NOT called
        mock_litellm.completion.assert_not_called()

    @patch("paperless.views.litellm")
    def test_connection_test_via_llm_proxy_endpoint(self, mock_litellm):
        """Test calling connection test via the generic llm_proxy endpoint."""
        mock_response = MagicMock()
        mock_litellm.completion.return_value = mock_response

        data = {
            "backend": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3",
        }

        # Note: the url pattern captures "test" as path
        response = self.client.post("/api/llm_proxy/test", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
