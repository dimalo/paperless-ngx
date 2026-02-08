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
        Get a LlamaIndex-compatible LLM instance for legacy integration.
        """
        from llama_index.llms.ollama import Ollama
        from llama_index.llms.openai import OpenAI

        if self.settings.llm_backend == "ollama":
            return Ollama(
                model=self.settings.llm_model or "llama3.1",
                base_url=self.settings.llm_endpoint or "http://localhost:11434",
                request_timeout=float(self.settings.llm_timeout or 120),
            )
        else:
            return OpenAI(
                model=self._get_model_with_prefix(),
                api_base=self.settings.llm_endpoint,
                api_key=self.settings.llm_api_key,
                timeout=float(self.settings.llm_timeout or 120),
            )

    def _get_model_with_prefix(self) -> str:
        """
        Get the model name with provider prefix for LiteLLM.
        """
        model = self.settings.llm_model or "llama3.1"
        backend = self.settings.llm_backend or "ollama"

        if "/" in model:
            return model

        return f"{backend}/{model}"

    def _clean_response(self, message) -> str:
        """
        Clean the LLM response by removing thinking/reasoning blocks.
        """
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            return (message.content or "").strip()

        content = message.content or ""
        if not content:
            return ""

        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

        if "<think>" in content:
            content = content.split("<think>")[0]

        if "</think>" in content:
            content = content.split("</think>", 1)[-1]

        return content.strip()

    def run_llm_query(self, prompt: str) -> dict:
        """
        Run an LLM query with structured output extraction.
        """
        model = self._get_model_with_prefix()
        logger.debug("Running LLM query against %s", model)

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
            response = litellm.completion(
                model=model,
                messages=messages,
                api_base=self.settings.llm_endpoint,
                api_key=self.settings.llm_api_key,
                timeout=self.settings.llm_timeout,
            )

            content = self._clean_response(response.choices[0].message)
            if not content:
                raise ValueError("LLM returned empty content")

            start_idx = content.find("{")
            end_idx = content.rfind("}")
            if start_idx != -1 and end_idx != -1:
                content = content[start_idx : end_idx + 1]

            return DocumentClassifierSchema.model_validate_json(content).model_dump()

        except Exception as e:
            logger.error("Structured extraction failed: %s", e)
            raise ValueError(f"Failed to extract document data: {e}") from e

    def run_chat(self, messages: list[dict]) -> str:
        """
        Run a chat completion query.
        """
        model = self._get_model_with_prefix()
        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                api_base=self.settings.llm_endpoint,
                api_key=self.settings.llm_api_key,
                timeout=self.settings.llm_timeout,
            )

            return self._clean_response(response.choices[0].message)

        except Timeout as e:
            raise Exception(
                f"LLM request timed out after {self.settings.llm_timeout}s.",
            ) from e
        except (APIError, APIConnectionError) as e:
            raise Exception(f"LLM API error: {e}") from e
