# Docling Backend Implementation Plan (Comprehensive)

## Overview

This document outlines the plan for porting the **Docling OCR Backend** from the massive feature branch (`feature/docling-ollama-ocr-backends`) to the new **OCR Broker** architecture. This implementation provides high-accuracy, layout-aware document parsing with structured Markdown output and semantic metadata mapping.

## Reference

**Source Branch:** `feature/docling-ollama-ocr-backends`
**Key Files to Reference:**

-   `src/paperless_docling/parsers.py` - Parser implementation
-   `src/paperless_docling/models.py` - Pydantic models for Docling responses
-   `src/paperless/config.py` - DoclingConfig dataclass
-   `src/paperless/models.py` - Configuration fields (lines with `docling_*`)
-   `src/paperless/settings.py` - Environment variable mappings

---

## 🟢 Phase 1: Core Infrastructure (COMPLETED ✅)

### 1. Unified Parser Architecture (`DoclingDocumentParser`)

...

-   **Resource Management:** Uses a lazily-loaded singleton for the `DocumentConverter` to avoid re-initializing heavy ML models for every document.

### 2. Configuration & Signal Registration

...

## 🟢 Phase 2: Rich Metadata & Debugging (COMPLETED ✅)

### A. Rich Metadata Mapping (Smart Enrichment)

Docling provides semantic labels and key-value pairs.

#### 1. Custom Field Mapping & Type Coercion

-   **Coercion:** Implemented a robust type-conversion layer (`_coerce_value`) for `INT`, `FLOAT`, `DATE`, `BOOLEAN`, and `MONETARY` fields.
-   **Synonyms:** Added a mapping for common metadata keys (e.g., `inv. no` -> `invoice number`).

#### 2. Automatic Semantic Tagging (Discovery)

-   **Strategy:** Automatically create tags with the prefix `Docling: ` (e.g., `Docling: Table`) and a distinct blue color (`#0066cc`).
-   **Logic:** Uses `get_or_create` to ensure the feature is useful out-of-the-box without manual setup.

### B. Caching & Decoupled Processing

Metadata extracted by the parser is stored in the Django cache using the `logging_group` as the key. A signal receiver retrieves this data after the document transaction commits to safely apply tags and custom fields.

---

## ⚪ Phase 3: Frontend & PDF Enhancement

### 1. Configuration UI

-   **AI Settings Tab:** Add Docling endpoint, force OCR, and language fields to the Angular UI.
-   **Priority List:** Ensure Docling appears in the drag-and-drop OCR priority list.

### 2. Searchable PDF Overlay (Optional Enhancement)

Generate a vector PDF with an invisible text layer using Docling's bounding boxes.

-   **Strategy:** Use `pikepdf` to add text layers to the original PDF without rasterizing the underlying document.
-   **Fallback:** Reference the massive branch's ReportLab implementation for images or corrupted PDFs.

---

## ⚪ Future Enhancements (Deferred)

1. **Fuzzy Matching:** Use `rapidfuzz` for better matching of "Inv. No" to "Invoice Number".
2. **Gotenberg Export:** Use `src/documents/gotenberg.py` to convert Docling's structured Markdown to a clean, formatted PDF/A.
3. **Interactive Mapping:** A UI prompt: _"Docling found 'Invoice No.' — map to Custom Field 'Invoice Number'? [Yes] [No]"_

---

## 🔍 Investigation Plans

### Question 1: Server Polling Strategy

-   **Issue:** Efficient polling for large documents without blocking worker threads too long.
-   **Plan:** Implement exponential backoff in `_convert_server` (1s -> 2s -> 5s -> 10s intervals) up to `docling_timeout`.

### Question 2: Dependency Management

-   **Issue:** Maintain `docling` as an optional dependency.
-   **Verification:** Ensure `is_docling_available()` in `signals.py` prevents parser registration if neither the library nor the endpoint is present.

### Question 3: Coordinate Systems

-   **Issue:** Docling models vary between `TOPLEFT` and `BOTTOMLEFT` origins.
-   **Plan:** Standardize on Paperless/ReportLab's `BOTTOMLEFT` using the `BoundingBox.to_normalized_origin_bottom_left()` method.

---

## ✅ Success Criteria

1. **Accuracy:** Search indexing includes structured table data from Markdown.
2. **Efficiency:** Automatic population of "Invoice Number" and "Total" custom fields.
3. **Quality:** Zero degradation of PDF quality (via Original Document First strategy).
4. **Developer Experience:** Clear debug artifacts available in the scratch directory.
