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

## 📋 Design Decisions

### Infrastructure & Dependencies

-   **Docker:** Switch `docker-compose.postgres.yml` to use `pgvector/pgvector:pg16` image to support vector extension.
-   **Dependencies:** Add `litellm` and `llama-index-vector-stores-postgres` to `pyproject.toml`.
-   **Permissions:** `LLMProxyView` restricted to `IsAdminUser` to prevent SSRF.

### Configuration Defaults

-   **Embedding Endpoint**: Defaults to `LLM_ENDPOINT` if not explicitly configured
-   **Embedding Model**: `nomic-embed-text:latest` (v2) for Ollama
-   **System Prompt**: Prepopulate with current hardcoded default, editable with reset button
-   **Timeouts**: Default 120s, but configurable via `llm_timeout` setting (up to 300s+ for CPU users).

### Error Handling

-   **Indexing Failures**: Skip document with warning (will retry on next scheduled index rebuild)
-   **Chat Failures**: Display actual litellm error to user via Paperless notification system
-   **Index Rebuild**: Detect dimension mismatch on model change, warn user with "Rebuild Index" button
-   **Postgres Extension**: Try `CREATE EXTENSION vector`. If permission denied, fail hard with instruction to run command as superuser.

### Vector Store Strategy

-   **PostgreSQL**: Use PGVector, fail hard if extension unavailable (no FAISS fallback)
-   **SQLite**: Use FAISS only
-   **Future**: Plan for Chroma as universal fallback

---

## 🔵 Phase 1: Backend Infrastructure (Pure Ollama Support)

### 1. Unified Configuration Model (`src/paperless/models.py`)

-   **Ollama Embeddings:** Add `OLLAMA` to `LLMEmbeddingBackend` choices.
-   **Separate Endpoints:** Introduce `llm_embedding_endpoint` and `llm_embedding_api_key` to allow decoupled LLM/Embedding services (defaults to main LLM config).
-   **Global Timeout:** Add `llm_timeout` (default 120s) to handle slower local models.
-   **System Prompt:** Add `ai_system_prompt` (TextField) with current hardcoded default prepopulated.

### 2. LiteLLM Client Layer (`src/paperless_ai/client.py`)

-   **Migration:** Replace direct `OpenAI`/`Ollama` classes with `litellm.completion` for broader backend compatibility.
-   **Reasoning Removal:** Implement `_clean_response` to strip `<think>...</think>` tags (crucial for DeepSeek Reasoner).
    -   Check `message.reasoning_content` first (LiteLLM feature).
    -   Fallback to regex removal for raw content.
    -   Handle unclosed/orphaned tags.
-   **JSON Robustness:** Use explicit schema injection in prompts and manual JSON extraction.

### 3. Ollama Embedding Backend (`src/paperless_ai/embedding.py`)

-   **Implementation:** Port `LiteLLMEmbedding` class to handle Ollama embedding calls via `litellm.embedding`.
-   **Default Model:** `nomic-embed-text:latest` (v2, 768 dimensions).
-   **Efficiency:** Implement parallel batch processing for initial document indexing.
-   **Dimension Discovery:** Logic to fetch embedding dimensions via Ollama's `/api/show` endpoint if `meta.json` missing.
-   **Model Change Detection:** Check stored dimension in `meta.json`, warn if mismatch detected.

---

## 🔵 Phase 2: Vector Store & Storage (PGVector Integration)

### 1. Database Support (`src/paperless_ai/vector_store.py`)

-   **PGVector:** Implement the `PGVectorStore` backend (using `llama-index-vector-stores-postgres`).
-   **Setup Logic:** check `pg_extension` table for `vector` extension.
-   **Configurable Backend:** Add `vector_store_backend` choice (AUTO/FAISS/POSTGRES) to the settings.
-   **Automatic Provisioning:** Logic to create the vector database/extension if permissions allow. **Fail hard** (raise exception) if PGVector selected but extension unavailable.

---

## 🔵 Phase 3: Frontend & Dynamic Configuration

### 1. Configuration UI (`src-ui/src/app/components/admin/settings/`)

-   **Dynamic Model Discovery:**
    -   Implement a "Refresh" button or trigger on endpoint change.
    -   Fetch available models via backend proxy (`GET /api/llm_proxy/?endpoint=X&backend=Y`).
    -   Convert model inputs into searchable dropdowns.
-   **System Prompt Editor:**
    -   Multi-line text field prepopulated with default.
    -   "Reset to Default" button to restore hardcoded prompt.
-   **Index Management:**
    -   Display warning banner if embedding model changed (dimension mismatch detected).
    -   "Rebuild Index" button to trigger `document_llmindex` task.
-   **Conditional Fields:** Hide/show API key and Endpoint fields based on the selected backend.

### 2. Backend Proxy (`src/paperless/views.py`)

-   **LLMProxyView:**
    -   **Permission:** `IsAdminUser` (strict security).
    -   `GET /api/llm_proxy/` - Proxy to Ollama `/api/tags` or return static OpenAI model list.
    -   `POST /api/llm_proxy/test` - Test connection to configured endpoint (fast path: `/api/version`).
    -   Normalize endpoint URLs (add http://, strip trailing slash).
    -   Return standardized `{id, name}[]` format.

### 3. LLM Service (`src-ui/src/app/services/llm.service.ts`)

-   Port `getModels(endpoint, backend)` method from reference branch.
-   Port `testConnection(config)` method for connection testing.
-   Handle errors gracefully, return empty array on failure.

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
