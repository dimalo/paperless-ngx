# Ollama AI Integration & Refined Configuration Plan

## Overview

This document outlines the plan for porting the **Ollama AI Integration** and **Refined Configuration Layer** from the massive feature branch (`feature/docling-ollama-ocr-backends`) to the current `dev` branch. The goal is to provide a "pure Ollama" experience, PGVector support, and a dynamic configuration UI with model discovery, while keeping OCR features out of scope for this specific task.

## Reference

**Source Branch:** `feature/docling-ollama-ocr-backends`
**Key Files to Reference:**

-   `src/paperless_ai/client.py` - LiteLLM integration & response cleaning
-   `src/paperless_ai/embedding.py` - Ollama/LiteLLM embedding support
-   `src/paperless_ai/vector_store.py` - PGVector integration
-   `src/paperless/models.py` - Configuration fields & choices
-   `src/paperless/settings.py` - Environment variable mappings
-   `src-ui/src/app/services/llm.service.ts` - Model discovery logic

---

## 🔵 Phase 1: Backend Infrastructure (Pure Ollama Support)

### 1. Unified Configuration Model (`src/paperless/models.py`)

-   **Ollama Embeddings:** Add `OLLAMA` to `LLMEmbeddingBackend` choices.
-   **Separate Endpoints:** Introduce `llm_embedding_endpoint` and `llm_embedding_api_key` to allow decoupled LLM/Embedding services.
-   **Global Timeout:** Add `llm_timeout` (default 120s) to handle slower local models.
-   **System Prompt:** Add `ai_system_prompt` to allow user-defined AI personas.

### 2. LiteLLM Client Layer (`src/paperless_ai/client.py`)

-   **Migration:** Replace direct `OpenAI`/`Ollama` classes with `litellm` for broader backend compatibility (OpenAI-compatible APIs, vLLM, etc.).
-   **Reasoning Removal:** Implement `_clean_response` to strip `<think>...</think>` tags (crucial for DeepSeek Reasoner and similar models).
-   **JSON Robustness:** Use explicit schema injection in prompts and manual JSON extraction for local models that struggle with API-level JSON mode.

### 3. Ollama Embedding Backend (`src/paperless_ai/embedding.py`)

-   **Implementation:** Port `LiteLLMEmbedding` class to handle Ollama embedding calls.
-   **Efficiency:** Implement parallel batch processing for initial document indexing.
-   **Dimension Discovery:** Logic to fetch embedding dimensions via Ollama's `/api/show` endpoint.

---

## 🔵 Phase 2: Vector Store & Storage (PGVector Integration)

### 1. Database Support (`src/paperless_ai/vector_store.py`)

-   **PGVector:** Implement the `PGVectorStore` backend to allow storing embeddings in PostgreSQL (requires PostgreSQL database backend and `pgvector` extension). Users running SQLite will continue using FAISS.
-   **Configurable Backend:** Add `vector_store_backend` choice (AUTO/FAISS/POSTGRES) to the settings. AUTO defaults to FAISS for SQLite and PGVector for PostgreSQL.
-   **Automatic Provisioning:** Logic to create the vector database/extension if permissions allow. Falls back to FAISS with a warning if provisioning fails.

---

## 🔵 Phase 3: Frontend & Dynamic Configuration

### 1. Configuration UI (`src-ui/src/app/components/admin/settings/`)

-   **Dynamic Model Discovery:**
    -   Implement a "Refresh" button or trigger on endpoint change.
    -   Fetch available models from `GET <endpoint>/api/tags` (Ollama) or `GET <endpoint>/v1/models` (OpenAI-compatible).
    -   Convert model inputs into searchable dropdowns.
-   **Conditional Fields:** Hide/show API key and Endpoint fields based on the selected backend.

### 2. LLM Service Enhancements (`src-ui/src/app/services/llm.service.ts`)

-   Update the service to proxy model discovery requests through the Paperless backend to avoid CORS issues with local Ollama instances.

---

## ✅ Success Criteria

1.  **Pure Local Mode:** Successfully index and chat using only Ollama (no OpenAI/HuggingFace).
2.  **Reasoning Support:** DeepSeek "thinking" blocks are correctly filtered from the UI.
3.  **UI UX:** Users can select models from a dropdown rather than typing "llama3.1:8b" manually.
4.  **Error Handling:**
    -   Timeouts log clear error messages indicating timeout duration and suggesting model may not be loaded.
    -   Connection errors return user-friendly messages with troubleshooting hints.
    -   Failed LLM queries don't crash the system; they log detailed errors and return graceful error responses to the UI.
5.  **Build Safety:** Ensure `litellm` and other new dependencies are correctly added to `pyproject.toml`.
