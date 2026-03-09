import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from pathlib import Path

import litellm
import requests
from django.conf import settings
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

from documents.models import Document
from paperless.config import AIConfig
from paperless.models import LLMEmbeddingBackend

logger = logging.getLogger("paperless_ai.embedding")


class LiteLLMEmbedding(BaseEmbedding):
    """
    Standardizes embedding calls using LiteLLM to support various backends.
    """

    model_name: str = ""
    api_base: str | None = None
    api_key: str | None = None
    timeout: int = 60
    MAX_RETRIES: int = 2
    BATCH_SIZE: int = 4

    def __init__(
        self,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        timeout: int = 60,
        **kwargs: Any,
    ) -> None:
        super().__init__(model_name=model_name, **kwargs)
        self.model_name = model_name
        self.api_base = api_base
        self.api_key = api_key
        self.timeout = timeout

    def _get_model_with_prefix(self) -> str:
        if "/" in self.model_name:
            return self.model_name
        return f"ollama/{self.model_name}"

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await self._aget_text_embedding(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        attempt = 0
        while True:
            try:
                response = litellm.embedding(
                    model=self._get_model_with_prefix(),
                    input=[text],
                    api_base=self.api_base,
                    api_key=self.api_key,
                    timeout=self.timeout,
                )
                return response.data[0]["embedding"]
            except (litellm.Timeout, litellm.APIError, litellm.APIConnectionError) as e:
                attempt += 1
                if attempt > self.MAX_RETRIES:
                    logger.error(
                        f"LiteLLM embedding call failed after {attempt} attempts: {e}",
                    )
                    raise
                logger.warning(
                    f"LiteLLM embedding call failed (attempt {attempt}/{self.MAX_RETRIES + 1}), retrying: {e}",
                )
                time.sleep(1)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        attempt = 0
        while True:
            try:
                response = await litellm.aembedding(
                    model=self._get_model_with_prefix(),
                    input=[text],
                    api_base=self.api_base,
                    api_key=self.api_key,
                    timeout=self.timeout,
                )
                return response.data[0]["embedding"]
            except (litellm.Timeout, litellm.APIError, litellm.APIConnectionError) as e:
                attempt += 1
                if attempt > self.MAX_RETRIES:
                    logger.error(
                        f"LiteLLM async embedding call failed after {attempt} attempts: {e}",
                    )
                    raise
                logger.warning(
                    f"LiteLLM async embedding call failed (attempt {attempt}/{self.MAX_RETRIES + 1}), retrying: {e}",
                )
                await asyncio.sleep(1)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        # Use asyncio to run aembedding in parallel
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self._aget_text_embeddings(texts))

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        batches = [
            texts[i : i + self.BATCH_SIZE]
            for i in range(0, len(texts), self.BATCH_SIZE)
        ]

        async def process_batch(batch_texts):
            attempt = 0
            while True:
                try:
                    response = await litellm.aembedding(
                        model=self._get_model_with_prefix(),
                        input=batch_texts,
                        api_base=self.api_base,
                        api_key=self.api_key,
                        timeout=self.timeout,
                    )
                    return [item["embedding"] for item in response.data]
                except (
                    litellm.Timeout,
                    litellm.APIError,
                    litellm.APIConnectionError,
                ) as e:
                    attempt += 1
                    if attempt > self.MAX_RETRIES:
                        logger.error(
                            f"LiteLLM async batch embedding call failed after {attempt} attempts: {e}",
                        )
                        raise
                    logger.warning(
                        f"LiteLLM async batch embedding call failed (attempt {attempt}/{self.MAX_RETRIES + 1}), retrying: {e}",
                    )
                    await asyncio.sleep(1)

        tasks = [process_batch(batch) for batch in batches]
        batch_results = await asyncio.gather(*tasks)

        all_embeddings = []
        for result in batch_results:
            all_embeddings.extend(result)
        return all_embeddings


def get_embedding_model() -> BaseEmbedding:
    config = AIConfig()
    logger.info(
        "Loading embedding model (backend: %s, model: %s)",
        config.llm_embedding_backend,
        config.llm_embedding_model or "default",
    )

    backend = config.llm_embedding_backend

    # Validate backend
    valid_backends = [choice[0] for choice in LLMEmbeddingBackend.choices]
    if backend not in valid_backends:
        raise ValueError(f"Unsupported embedding backend: {backend}")

    if backend == LLMEmbeddingBackend.OPENAI:
        # Check if using custom endpoint (OpenAI-compatible but not official API)
        custom_endpoint = config.llm_embedding_endpoint or config.llm_endpoint
        if custom_endpoint and custom_endpoint != "https://api.openai.com/v1":
            # Use LiteLLM for custom endpoints to avoid model name validation
            return LiteLLMEmbedding(
                model_name=str(config.llm_embedding_model or "text-embedding-3-small"),
                api_base=str(custom_endpoint),
                api_key=str(config.llm_embedding_api_key or config.llm_api_key or ""),
                timeout=int(config.llm_timeout or 60),
            )
        return OpenAIEmbedding(
            model=str(config.llm_embedding_model or "text-embedding-3-small"),
            api_key=str(config.llm_api_key or ""),
        )
    elif backend == LLMEmbeddingBackend.HUGGINGFACE:
        return HuggingFaceEmbedding(
            model_name=str(
                config.llm_embedding_model or "sentence-transformers/all-MiniLM-L6-v2",
            ),
        )
    elif backend == LLMEmbeddingBackend.OLLAMA:
        return LiteLLMEmbedding(
            model_name=str(config.llm_embedding_model or "nomic-embed-text"),
            api_base=str(
                config.llm_embedding_endpoint or config.llm_endpoint or "",
            ),
            api_key=str(config.llm_embedding_api_key or config.llm_api_key or ""),
            timeout=int(config.llm_timeout or 60),
        )
    else:
        # Fallback/Legacy
        return OpenAIEmbedding(
            model=str(config.llm_embedding_model or "text-embedding-3-small"),
            api_key=str(config.llm_api_key or ""),
        )


def get_embedding_dim() -> int:
    """
    Loads embedding dimension from meta.json or infers it.
    """
    config = AIConfig()
    if config.llm_embedding_backend == LLMEmbeddingBackend.OPENAI:
        model = config.llm_embedding_model or "text-embedding-3-small"
    elif config.llm_embedding_backend == LLMEmbeddingBackend.OLLAMA:
        model = config.llm_embedding_model or "nomic-embed-text"
    elif config.llm_embedding_backend == LLMEmbeddingBackend.HUGGINGFACE:
        model = config.llm_embedding_model or "sentence-transformers/all-MiniLM-L6-v2"
    else:
        model = config.llm_embedding_model or "unknown"

    meta_path: Path = settings.LLM_INDEX_DIR / "meta.json"
    if meta_path.exists():
        with meta_path.open() as f:
            meta = json.load(f)
        if meta.get("embedding_model") != model:
            raise RuntimeError(
                f"Embedding model changed from {meta.get('embedding_model')} to {model}. Rebuild index.",
            )
        return meta["dim"]

    # Try Ollama discovery
    endpoint_url = config.llm_embedding_endpoint or config.llm_endpoint
    if config.llm_embedding_backend == LLMEmbeddingBackend.OLLAMA and endpoint_url:
        try:
            endpoint = endpoint_url.rstrip("/")
            if not endpoint.startswith("http"):
                endpoint = f"http://{endpoint}"
            show_url = f"{endpoint}/api/show"
            resp = requests.post(show_url, json={"name": model}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                model_info = data.get("model_info", {})
                if "embedding_length" in model_info:
                    return int(model_info["embedding_length"])
                if "llama.embedding_length" in model_info:
                    return int(model_info["llama.embedding_length"])
        except Exception as e:
            logger.debug(f"Failed to fetch model info from Ollama: {e}")

    embedding_model = get_embedding_model()
    dim = len(embedding_model.get_text_embedding("test"))

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with meta_path.open("w") as f:
        json.dump({"embedding_model": model, "dim": dim}, f)

    return dim


def build_llm_index_text(doc: Document) -> str:
    lines = [
        f"Title: {doc.title}",
        f"Filename: {doc.filename}",
        f"Created: {doc.created}",
        f"Added: {doc.added}",
        f"Modified: {doc.modified}",
        f"Tags: {', '.join(tag.name for tag in doc.tags.all())}",  # type: ignore
        f"Document Type: {doc.document_type.name if doc.document_type else ''}",
        f"Correspondent: {doc.correspondent.name if doc.correspondent else ''}",
        f"Storage Path: {doc.storage_path.name if doc.storage_path else ''}",
        f"Archive Serial Number: {doc.archive_serial_number or ''}",
        f"Notes: {','.join([str(n.note) for n in doc.notes.all()])}",
    ]

    for instance in doc.custom_fields.all():  # type: ignore
        lines.append(f"Custom Field - {instance.field.name}: {instance}")

    lines.append("\nContent:\n")
    lines.append(str(doc.content or ""))

    return "\n".join(lines)
