import json
import logging

import litellm
from litellm.exceptions import APIConnectionError
from litellm.exceptions import APIError
from litellm.exceptions import Timeout

from paperless.config import AIConfig
from paperless_ai.base_model import DocumentClassifierSchema

logger = logging.getLogger("paperless_ai.client")


class AIClient:
    """
    A client for interacting with an LLM backend using LiteLLM.
    """

    def __init__(self):
        self.settings = AIConfig()

    def _get_model_with_prefix(self) -> str:
        """
        Get the model name with provider prefix for LiteLLM.

        For backward compatibility, if the model doesn't have a prefix,
        prepend the backend name (e.g., "llama3.1" -> "ollama/llama3.1").
        """
        model = self.settings.llm_model or "llama3.1"
        backend = self.settings.llm_backend or "ollama"

        # If model already has a prefix (contains /), use as-is
        if "/" in model:
            return model

        # Otherwise, prepend the backend as prefix
        return f"{backend}/{model}"

    def run_llm_query(self, prompt: str) -> dict:
        """
        Run an LLM query with function calling to extract structured data.

        Args:
            prompt: The prompt to send to the LLM

        Returns:
            Dictionary with extracted document classification data

        Raises:
            Exception: If LLM query fails or returns invalid data
        """
        logger.debug(
            "Running LLM query against %s with model %s",
            self.settings.llm_backend,
            self.settings.llm_model,
        )

        model = self._get_model_with_prefix()

        # Build tool calling schema from Pydantic model
        # Using modern 'tools' parameter instead of deprecated 'functions'
        tool_schema = {
            "type": "function",
            "function": {
                "name": "classify_document",
                "description": "Classify a document and extract metadata",
                "parameters": DocumentClassifierSchema.model_json_schema(),
            },
        }

        messages = [{"role": "user", "content": prompt}]

        last_exception = None

        # Attempt 1: Try with native tool calling
        try:
            logger.debug("Attempt 1: Using native tool calling")
            # ... (implementation)
            response = litellm.completion(
                model=model,
                messages=messages,
                tools=[tool_schema],
                stream=False,
                tool_choice={
                    "type": "function",
                    "function": {"name": "classify_document"},
                },
                api_base=self.settings.llm_endpoint,
                api_key=self.settings.llm_api_key,
                timeout=self.settings.llm_timeout,
            )

            message = response.choices[0].message

            # Check for valid tool call
            if hasattr(message, "tool_calls") and message.tool_calls:
                function_args = message.tool_calls[0].function.arguments
                if isinstance(function_args, str):
                    function_args = json.loads(function_args)
                logger.debug("Attempt 1 successful with tool call")
                return DocumentClassifierSchema(**function_args).model_dump()

            # Check for valid JSON in content (fallback for misbehaving tool models)
            if message.content:
                content = message.content.strip()
                start_idx = content.find("{")
                end_idx = content.rfind("}")
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    possible_json = content[start_idx : end_idx + 1]
                    logger.debug("Attempt 1 successful with JSON in content")
                    return DocumentClassifierSchema(
                        **json.loads(possible_json),
                    ).model_dump()

            logger.warning(
                "Attempt 1 failed: No tool call or JSON content found. Content length: %d",
                len(message.content or ""),
            )

        except Exception as e:
            logger.warning(f"Attempt 1 failed with error: {e}")
            last_exception = e

        # Attempt 2: Retry with JSON mode (no tools)
        logger.debug("Attempt 2: Retrying with JSON mode and explicit schema")

        # Prepare system prompt with schema
        schema_json = json.dumps(DocumentClassifierSchema.model_json_schema(), indent=2)
        system_prompt = (
            f"You are a document classifier. "
            f"Classify the document and extract metadata. "
            f"Output strictly valid JSON matching this schema:\n{schema_json}"
        )

        retry_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        try:
            response = litellm.completion(
                model=model,
                messages=retry_messages,
                stream=False,
                api_base=self.settings.llm_endpoint,
                api_key=self.settings.llm_api_key,
                timeout=self.settings.llm_timeout,
            )

            message = response.choices[0].message
            content = message.content or ""
            start_idx = content.find("{")
            end_idx = content.rfind("}")

            if start_idx != -1 and end_idx != -1:
                content = content[start_idx : end_idx + 1]
                data = json.loads(content)
                logger.debug("Attempt 2 successful")
                return DocumentClassifierSchema(**data).model_dump()

            logger.warning("Attempt 2 failed: JSON delimiters not found")

        except Exception as e:
            logger.error(f"Attempt 2 failed: {e}")
            last_exception = e

        # If we get here, both attempts failed
        # Log the content of the LAST attempt for debugging purposes
        safe_content = ""
        if "response" in locals():
            try:
                # Try to use Pydantic's built-in JSON serialization if available (LiteLLM responses are Pydantic models)
                if hasattr(response, "model_dump_json"):
                    safe_content = response.model_dump_json(indent=2)
                elif hasattr(response, "json") and callable(response.json):
                    # Some older versions or specific types might use .json()
                    safe_content = response.json(indent=2)
                else:
                    # Fallback: try to dump via dict/attributes or just str
                    safe_content = str(response)
            except Exception:
                safe_content = str(response)

        # Log the detailed response at DEBUG level
        logger.debug("Final Failure Response: %s", safe_content)

        error_msg = f"Failed to extract document classification data after 2 attempts. Response: {safe_content}"
        if last_exception:
            error_msg += f" Last Error: {last_exception}"

        raise ValueError(error_msg)

    def run_chat(self, messages: list[dict]) -> str:
        """
        Run a chat completion query.

        Args:
            messages: List of message dictionaries with 'role' and 'content'

        Returns:
            The assistant's response text

        Raises:
            Exception: If LLM query fails
        """
        logger.debug(
            "Running chat query against %s with model %s",
            self.settings.llm_backend,
            self.settings.llm_model,
        )

        model = self._get_model_with_prefix()

        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                api_base=self.settings.llm_endpoint,
                api_key=self.settings.llm_api_key,
                timeout=self.settings.llm_timeout,
            )

            result = response.choices[0].message.content
            logger.debug("Chat result: %s", result)
            return result

        except Timeout as e:
            logger.error(
                "LLM request timed out (limit: %ss). Check if model is loaded.",
                self.settings.llm_timeout,
            )
            raise Exception(
                f"LLM request timed out after {self.settings.llm_timeout}s. "
                "Check if the model is loaded and the endpoint is reachable.",
            ) from e
        except (APIError, APIConnectionError) as e:
            logger.error("LLM API error: %s", e)
            raise Exception(f"LLM API error: {e}") from e
