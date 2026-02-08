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

from documents.models import Document
from documents.models import Note
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
            except Exception:
                attempt += 1
                if attempt > self.MAX_RETRIES:
                    raise
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
            except Exception:
                attempt += 1
                if attempt > self.MAX_RETRIES:
                    raise
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
            response = await litellm.aembedding(
                model=self._get_model_with_prefix(),
                input=batch_texts,
                api_base=self.api_base,
                api_key=self.api_key,
                timeout=self.timeout,
            )
            return [item["embedding"] for item in response.data]

        all_embeddings = []
        tasks = [process_batch(batch) for batch in batches]
        batch_results = await asyncio.gather(*tasks)

        for result in batch_results:
            all_embeddings.extend(result)
        return all_embeddings


def get_embedding_model() -> BaseEmbedding:
    config = AIConfig()
    match config.llm_embedding_backend:
        case LLMEmbeddingBackend.HUGGINGFACE:
            return HuggingFaceEmbedding(
                model_name=str(
                    config.llm_embedding_model
                    or "sentence-transformers/all-MiniLM-L6-v2",
                ),
            )
        case LLMEmbeddingBackend.OLLAMA:
            return LiteLLMEmbedding(
                model_name=str(config.llm_embedding_model or "nomic-embed-text"),
                api_base=str(
                    config.llm_embedding_endpoint or config.llm_endpoint or "",
                ),
                api_key=str(config.llm_embedding_api_key or config.llm_api_key or ""),
                timeout=int(config.llm_timeout or 60),
            )
        case _:
            # Fallback/Legacy
            from llama_index.embeddings.openai import OpenAIEmbedding

            return OpenAIEmbedding(
                model=str(config.llm_embedding_model or "text-embedding-3-small"),
                api_key=str(config.llm_api_key or ""),
            )


def get_embedding_dim() -> int:
    """
    Loads embedding dimension from meta.json or infers it.
    """
    config = AIConfig()
    model = config.llm_embedding_model or (
        "nomic-embed-text"
        if config.llm_embedding_backend == LLMEmbeddingBackend.OLLAMA
        else "sentence-transformers/all-MiniLM-L6-v2"
    )

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
    if config.llm_embedding_backend == LLMEmbeddingBackend.OLLAMA:
        try:
            endpoint = (
                config.llm_embedding_endpoint or config.llm_endpoint or ""
            ).rstrip("/")
            if endpoint:
                if not endpoint.startswith("http"):
                    endpoint = f"http://{endpoint}"
                resp = requests.post(f"{endpoint}/api/show", json={"name": model})
                if resp.status_code == 200:
                    info = resp.json().get("model_info", {})
                    dim = info.get("embedding_length") or info.get(
                        "llama.embedding_length",
                    )
                    if dim:
                        return int(dim)
        except Exception:
            pass

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
        f"Tags: {', '.join(tag.name for tag in doc.tags.all())}",
        f"Document Type: {doc.document_type.name if doc.document_type else ''}",
        f"Correspondent: {doc.correspondent.name if doc.correspondent else ''}",
        f"Storage Path: {doc.storage_path.name if doc.storage_path else ''}",
        f"Archive Serial Number: {doc.archive_serial_number or ''}",
        f"Notes: {','.join([str(c.note) for c in Note.objects.filter(document=doc)])}",
    ]

    for instance in doc.custom_fields.all():
        lines.append(f"Custom Field - {instance.field.name}: {instance}")

    lines.append("\nContent:\n")
    lines.append(doc.content or "")

    return "\n".join(lines)
