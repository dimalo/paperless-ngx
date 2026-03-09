import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from paperless_ai.client import AIClient


@pytest.fixture
def mock_ai_config():
    with patch("paperless_ai.client.AIConfig") as MockAIConfig:
        mock_config = MagicMock()
        mock_config.llm_backend = "ollama"
        mock_config.llm_model = "llama3.1"
        mock_config.llm_endpoint = "http://localhost:11434"
        mock_config.llm_api_key = None
        mock_config.llm_timeout = 120
        MockAIConfig.return_value = mock_config
        yield mock_config


def test_get_model_with_prefix_no_prefix(mock_ai_config):
    """Test that model names without prefix get backend prepended."""
    mock_ai_config.llm_backend = "ollama"
    mock_ai_config.llm_model = "llama3.1"

    client = AIClient()
    assert client._get_model_with_prefix() == "ollama/llama3.1"


def test_get_model_with_prefix_has_prefix(mock_ai_config):
    """Test that model names with prefix are used as-is."""
    mock_ai_config.llm_backend = "ollama"
    mock_ai_config.llm_model = "openai/gpt-4"

    client = AIClient()
    assert client._get_model_with_prefix() == "openai/gpt-4"


def test_get_model_with_prefix_openai(mock_ai_config):
    """Test OpenAI backend model prefix."""
    mock_ai_config.llm_backend = "openai"
    mock_ai_config.llm_model = "gpt-3.5-turbo"

    client = AIClient()
    assert client._get_model_with_prefix() == "openai/gpt-3.5-turbo"


@patch("paperless_ai.client.litellm")
def test_run_llm_query_success(mock_litellm, mock_ai_config):
    """Test successful LLM query with structured output extraction."""
    # Mock response with JSON content (matching updated implementation)
    mock_response_content = {
        "title": "Test Title",
        "title_confidence": 0.9,
        "tags": ["test", "document"],
        "tags_confidence": {"test": 0.85, "document": 0.95},
        "correspondents": ["John Doe"],
        "correspondents_confidence": {"John Doe": 0.8},
        "document_types": ["report"],
        "document_types_confidence": {"report": 0.75},
        "storage_paths": ["Reports"],
        "storage_paths_confidence": {"Reports": 0.9},
        "dates": ["2023-01-01"],
    }

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(mock_response_content)
    mock_response.choices[0].message.reasoning_content = None

    mock_litellm.completion.return_value = mock_response

    client = AIClient()
    result = client.run_llm_query("test_prompt")

    assert result["title"] == "Test Title"
    assert result["tags"] == ["test", "document"]

    # Verify litellm.completion was called with correct parameters
    mock_litellm.completion.assert_called_once()
    call_kwargs = mock_litellm.completion.call_args.kwargs
    assert call_kwargs["model"] == "ollama/llama3.1"
    assert call_kwargs["timeout"] == 120
    assert call_kwargs["api_base"] == "http://localhost:11434"
    # Verify we're NOT using tools parameter anymore
    assert "tools" not in call_kwargs
    assert "tool_choice" not in call_kwargs


@patch("paperless_ai.client.litellm")
def test_run_llm_query_timeout(mock_litellm, mock_ai_config):
    """Test LLM query timeout handling."""
    from litellm.exceptions import Timeout

    mock_litellm.completion.side_effect = Timeout(
        "Request timed out",
        model="ollama/llama3.1",
        llm_provider="ollama",
    )

    client = AIClient()

    with pytest.raises(Exception, match="Failed to extract document data"):
        client.run_llm_query("test_prompt")


@patch("paperless_ai.client.litellm")
def test_run_llm_query_api_error(mock_litellm, mock_ai_config):
    """Test LLM query API error handling."""
    from litellm.exceptions import APIError

    mock_litellm.completion.side_effect = APIError(
        status_code=500,
        message="API error",
        llm_provider="ollama",
        model="ollama/llama3.1",
    )

    client = AIClient()

    with pytest.raises(Exception, match="Failed to extract document data"):
        client.run_llm_query("test_prompt")


@patch("paperless_ai.client.litellm")
def test_run_chat_success(mock_litellm, mock_ai_config):
    """Test successful chat completion."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "test_chat_result"

    mock_litellm.completion.return_value = mock_response

    client = AIClient()
    messages = [{"role": "user", "content": "Hello"}]
    result = client.run_chat(messages)

    assert result == "test_chat_result"

    # Verify litellm.completion was called with correct parameters
    mock_litellm.completion.assert_called_once()
    call_kwargs = mock_litellm.completion.call_args.kwargs
    assert call_kwargs["model"] == "ollama/llama3.1"
    assert call_kwargs["messages"] == messages
    assert call_kwargs["timeout"] == 120


@patch("paperless_ai.client.litellm")
def test_run_chat_timeout(mock_litellm, mock_ai_config):
    """Test chat timeout handling."""
    from litellm.exceptions import Timeout

    mock_litellm.completion.side_effect = Timeout(
        "Request timed out",
        model="ollama/llama3.1",
        llm_provider="ollama",
    )

    client = AIClient()

    with pytest.raises(Exception, match="LLM request timed out"):
        client.run_chat([{"role": "user", "content": "Hello"}])


@patch("paperless_ai.client.litellm")
def test_run_chat_api_connection_error(mock_litellm, mock_ai_config):
    """Test chat API connection error handling."""
    from litellm.exceptions import APIConnectionError

    mock_litellm.completion.side_effect = APIConnectionError(
        message="Connection error",
        llm_provider="ollama",
        model="ollama/llama3.1",
    )

    client = AIClient()

    with pytest.raises(Exception, match="LLM API error"):
        client.run_chat([{"role": "user", "content": "Hello"}])
