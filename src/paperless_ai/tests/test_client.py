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
    """Test successful LLM query with tool calling."""
    # Mock tool call response (new format using tools parameter)
    mock_tool_call = MagicMock()
    mock_tool_call.function.arguments = {
        "title": "Test Title",
        "tags": ["test", "document"],
        "correspondents": ["John Doe"],
        "document_types": ["report"],
        "storage_paths": ["Reports"],
        "dates": ["2023-01-01"],
    }

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.tool_calls = [mock_tool_call]

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
    # Verify we're using tools parameter instead of deprecated functions
    assert "tools" in call_kwargs
    assert "tool_choice" in call_kwargs


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

    with pytest.raises(Exception, match="LLM request timed out"):
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

    with pytest.raises(Exception, match="LLM API error"):
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


@patch("paperless_ai.client.litellm")
def test_run_llm_query_retry_mechanism_malformed_response(mock_litellm, mock_ai_config):
    """Test retry mechanism logging uses model_dump_json if available."""

    # Attempt 1: Fail (empty)
    mock_response_fail1 = MagicMock()
    mock_response_fail1.choices = [MagicMock()]
    mock_response_fail1.choices[0].message.tool_calls = None
    mock_response_fail1.choices[0].message.content = ""

    # Attempt 2: Malformed response but has model_dump_json
    mock_response_malformed = MagicMock()
    del mock_response_malformed.choices  # Simulate missing choices
    mock_response_malformed.model_dump_json.return_value = '{"error": "formatted_json"}'

    # Configure side_effect
    mock_litellm.completion.side_effect = [mock_response_fail1, mock_response_malformed]

    client = AIClient()

    # Verify exception uses formatted json
    with pytest.raises(ValueError, match=r'Response: \{"error": "formatted_json"\}'):
        client.run_llm_query("test_prompt")

    assert mock_litellm.completion.call_count == 2
    mock_response_malformed.model_dump_json.assert_called_once()
