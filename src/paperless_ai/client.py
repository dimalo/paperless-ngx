import json
import logging
import re

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

    def __init__(self) -> None:
        self.settings = AIConfig()

    @property
    def llm(self):
        """
        Get a LlamaIndex-compatible LLM instance.
        """
        from llama_index.llms.ollama import Ollama
        from llama_index.llms.openai import OpenAI

        # For LlamaIndex, we use the specific integration based on the backend
        if self.settings.llm_backend == "ollama":
            return Ollama(
                model=self.settings.llm_model or "llama3.1",
                base_url=self.settings.llm_endpoint or "http://localhost:11434",
                request_timeout=float(self.settings.llm_timeout or 120),
            )
        else:
            # For other providers (OpenAI, Azure, Anthropic, etc.),
            # we use the OpenAI class which is LiteLLM-compatible if the endpoint is set
            return OpenAI(
                model=self._get_model_with_prefix(),
                api_base=self.settings.llm_endpoint,
                api_key=self.settings.llm_api_key,
                timeout=float(self.settings.llm_timeout or 120),
            )

    def _get_model_with_prefix(self) -> str:
        """
        Get the model name with provider prefix for LiteLLM.

        For backward compatibility, if the model doesn't have a prefix,
        prepend the backend name (e.g., "llama3.1" -> "ollama/llama3.1").
        When using a custom endpoint (api_base set), we add the "openai/" prefix
        so LiteLLM knows it's an OpenAI-compatible API.
        """
        model = self.settings.llm_model or "llama3.1"
        backend = self.settings.llm_backend or "ollama"

        # If model already has a prefix (contains /), use as-is
        if "/" in model:
            return model

        # If using a custom endpoint (not official OpenAI API), use openai/ prefix
        # so LiteLLM knows which API format to use
        if self.settings.llm_endpoint:
            return f"openai/{model}"

        # Otherwise, prepend the backend as prefix
        return f"{backend}/{model}"

    def _clean_response(self, message) -> str:
        """
        Clean the LLM response by removing thinking/reasoning blocks.
        Supports both LiteLLM's reasoning_content field and fallback string cleaning.
        """
        # 1. Check if LiteLLM already separated the reasoning content
        # (available for DeepSeek Reasoner, OpenAI o1, etc.)
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            logger.debug("Detected separate reasoning_content from LiteLLM")
            return (message.content or "").strip()

        content = message.content or ""
        if not content:
            return ""

        # 2. Fallback: Remove <think>...</think> blocks if they are embedded in content
        # This often happens with local Ollama/vLLM setups or older LiteLLM versions.

        # First, remove properly paired <think>...</think> blocks
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

        # Handle unclosed <think> tags (if truncated) - keep everything before
        if "<think>" in content:
            content = content.split("<think>")[0]

        # Handle orphaned </think> tags (when opening tag was earlier) - keep everything after
        if "</think>" in content:
            content = content.split("</think>", 1)[-1]

        return content.strip()

    def run_llm_query(self, prompt: str) -> dict:
        """
        Run an LLM query with structured output to extract metadata.
        Uses explicit schema injection and JSON mode for maximum compatibility across backends.
        """
        model = self._get_model_with_prefix()
        backend = self.settings.llm_backend
        logger.debug("Running LLM query against %s (%s)", model, backend)

        # Build a prompt that explicitly includes the schema
        schema_json = DocumentClassifierSchema.model_json_schema()
        full_prompt = (
            f"{prompt}\n\n"
            f"INSTRUCTIONS: You are a pure data extraction backend. Output ONLY a valid JSON object matching this schema. "
            f"Do not repeat the prompt. Do not add markdown or conversational text.\n"
            f"SCHEMA:\n{json.dumps(schema_json, indent=2)}\n\n"
            f"JSON RESPONSE:"
        )

        messages = [{"role": "user", "content": full_prompt}]

        try:
            # We skip response_format={"type": "json_object"} as it caused hallucinations
            # on some Ollama models. We rely on the prompt + manual extraction.
            response = litellm.completion(
                model=model,
                messages=messages,
                stream=False,
                api_base=self.settings.llm_endpoint,
                api_key=self.settings.llm_api_key,
                timeout=self.settings.llm_timeout,
            )

            content = self._clean_response(response.choices[0].message)
            if not content:
                raise ValueError("LLM returned empty content")

            # Extract JSON from potential markdown or conversational text
            start_idx = content.find("{")
            end_idx = content.rfind("}")
            if start_idx != -1 and end_idx != -1:
                content = content[start_idx : end_idx + 1]

            # Validate against the Pydantic model
            return DocumentClassifierSchema.model_validate_json(content).model_dump()

        except Exception as e:
            # Enhanced error logging
            raw_content = "unknown"
            if "response" in locals() and hasattr(response, "choices"):
                try:
                    raw_content = response.choices[0].message.content
                except Exception:
                    pass
            logger.error(
                "Structured extraction failed. Raw content: %s. Error: %s",
                raw_content,
                e,
            )
            # Re-raise with a clear message
            raise ValueError(f"Failed to extract document data: {e}") from e

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
                stream=False,
                api_base=self.settings.llm_endpoint,
                api_key=self.settings.llm_api_key,
                timeout=self.settings.llm_timeout,
            )

            result = self._clean_response(response.choices[0].message)
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
