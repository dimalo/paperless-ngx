import json
import logging
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
from documents.models import Note
from paperless.config import AIConfig
from paperless.models import LLMEmbeddingBackend

logger = logging.getLogger("paperless_ai.embedding")


class LiteLLMEmbedding(BaseEmbedding):
    """
    Standardizes embedding calls using LiteLLM to support various backends,
    specifically Ollama for this implementation.
    """

    model_name: str = ""
    api_base: str | None = None
    api_key: str | None = None
    timeout: int = 60

    def __init__(
        self,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        timeout: int = 60,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            **kwargs,
        )
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
        response = litellm.embedding(
            model=self._get_model_with_prefix(),
            input=[text],
            api_base=self.api_base,
            api_key=self.api_key,
            timeout=self.timeout,
        )
        return response.data[0]["embedding"]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        response = await litellm.aembedding(
            model=self._get_model_with_prefix(),
            input=[text],
            api_base=self.api_base,
            api_key=self.api_key,
            timeout=self.timeout,
        )
        return response.data[0]["embedding"]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        response = litellm.embedding(
            model=self._get_model_with_prefix(),
            input=texts,
            api_base=self.api_base,
            api_key=self.api_key,
            timeout=self.timeout,
        )
        return [item["embedding"] for item in response.data]


def get_embedding_model() -> BaseEmbedding:
    config = AIConfig()

    match config.llm_embedding_backend:
        case LLMEmbeddingBackend.OPENAI:
            return OpenAIEmbedding(
                model=config.llm_embedding_model or "text-embedding-3-small",
                api_key=config.llm_api_key,
            )
        case LLMEmbeddingBackend.HUGGINGFACE:
            return HuggingFaceEmbedding(
                model_name=config.llm_embedding_model
                or "sentence-transformers/all-MiniLM-L6-v2",
            )
        case LLMEmbeddingBackend.OLLAMA:
            return LiteLLMEmbedding(
                model_name=config.llm_embedding_model or "nomic-embed-text",
                api_base=config.llm_embedding_endpoint or config.llm_endpoint,
                api_key=config.llm_embedding_api_key or config.llm_api_key,
                timeout=int(config.llm_timeout or 60),
            )
        case _:
            raise ValueError(
                f"Unsupported embedding backend: {config.llm_embedding_backend}",
            )


def get_embedding_dim() -> int:
    """
    Loads embedding dimension from meta.json if available, otherwise infers it
    from a dummy embedding and stores it for future use.
    """
    config = AIConfig()
    if config.llm_embedding_backend == LLMEmbeddingBackend.OPENAI:
        model = config.llm_embedding_model or "text-embedding-3-small"
    elif config.llm_embedding_backend == LLMEmbeddingBackend.OLLAMA:
        model = config.llm_embedding_model or "nomic-embed-text"
    elif config.llm_embedding_backend == LLMEmbeddingBackend.HUGGINGFACE:
        model = config.llm_embedding_model or "sentence-transformers/all-MiniLM-L6-v2"
    else:
        raise ValueError(
            f"Unsupported embedding backend: {config.llm_embedding_backend}",
        )

    meta_path: Path = settings.LLM_INDEX_DIR / "meta.json"
    if meta_path.exists():
        with meta_path.open() as f:
            meta = json.load(f)
        if meta.get("embedding_model") != model:
            raise RuntimeError(
                f"Embedding model changed from {meta.get('embedding_model')} to {model}. "
                "You must rebuild the index.",
            )
        return meta["dim"]

    # Try to fetch from Ollama API if applicable
    endpoint_url = config.llm_embedding_endpoint or config.llm_endpoint
    if config.llm_embedding_backend == LLMEmbeddingBackend.OLLAMA and endpoint_url:
        try:
            endpoint = endpoint_url.rstrip(
                "/",
            )
            if not endpoint.startswith("http"):
                endpoint = f"http://{endpoint}"
            show_url = f"{endpoint}/api/show"
            resp = requests.post(show_url, json={"name": model}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                # Embedding dimension can often be found in model info or parameters
                # Look specifically for 'embedding_length' or similar fields in the response
                # DeepSeek-based models and others often have this in the info.
                model_info = data.get("model_info", {})
                if "embedding_length" in model_info:
                    return int(model_info["embedding_length"])
                # Fallback to other possible locations
                if "llama.embedding_length" in model_info:
                    return int(model_info["llama.embedding_length"])
        except Exception as e:
            logger.debug(f"Failed to fetch model info from Ollama: {e}")

    embedding_model = get_embedding_model()
    test_embed = embedding_model.get_text_embedding("test")
    dim = len(test_embed)

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
        f"Tags: {', '.join(tag.name for tag in doc.tags.all())}",
        f"Document Type: {doc.document_type.name if doc.document_type else ''}",
        f"Correspondent: {doc.correspondent.name if doc.correspondent else ''}",
        f"Storage Path: {doc.storage_path.name if doc.storage_path else ''}",
        f"Archive Serial Number: {doc.archive_serial_number or ''}",
        f"Notes: {','.join([str(c.note) for c in Note.objects.filter(document=doc)])}",
    ]

    for instance in doc.custom_fields.all():  # type: ignore
        lines.append(f"Custom Field - {instance.field.name}: {instance}")

    lines.append("\nContent:\n")
    lines.append(doc.content or "")

    return "\n".join(lines)
