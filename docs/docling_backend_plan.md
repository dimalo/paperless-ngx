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

The parser determines its execution path based on the `docling_endpoint` setting.

**Decision Tree:**

```python
IF docling_endpoint is set:
    Use _convert_server() -> HTTP POST to Docling-serve API -> Poll for task completion
ELSE:
    Use _convert_local() -> Import 'docling' library -> Process locally
```

**Key Implementation Details:**

-   **Markdown Source:** Uses `md_content` for `self.text` to preserve tables/headers for the search index.
-   **Sanitization:** Regex-based removal of base64 images from Markdown to keep the DB clean.
-   **Archive Strategy:** Returns the **original document** as archive by default to preserve vector quality and prevent rasterization artifacts.

### 2. Configuration & Signal Registration

-   **Database:** Added `docling_endpoint`, `docling_force_ocr`, `docling_language`, `docling_timeout`.
-   **Config Class:** `DoclingConfig` with automatic endpoint normalization (`http://` prefixing).
-   **Broker Hook:** Registered `engine_id: "docling"` via `document_consumer_declaration`.

---

## 🟡 Phase 2: Rich Metadata & Debugging (IN PROGRESS 🔄)

### A. Rich Metadata Mapping (Smart Enrichment)

Docling provides semantic labels and key-value pairs. We will map these to Paperless-ngx features without creating "tag spam."

#### 1. Custom Field Mapping

-   **Logic:** Map `key_value_items` (e.g., `{"key": "Invoice Number", "value": "123"}`) to existing Custom Fields.
-   **Matching:** Case-insensitive exact match (Phase 2.1) -> Lookup map for synonyms (Phase 2.2).
-   **Confidence:** Only apply if Docling confidence > 0.8 (if available).

#### 2. Semantic Labels to Tags

-   **Labels:** Docling identifies `TABLE`, `FORMULA`, `HANDWRITTEN`, `KEY_VALUE_REGION`.
-   **Tagging Rule:** Only apply semantic tags (e.g., `Docling: Table`) if they **already exist** in the system.
-   **Discovery Log:** If metadata is found but no mapping/tag exists, log a summary:
    -   `[Docling] Detected semantic features: Table, Handwritten Text`
    -   `[Docling] Found unmapped metadata: { "Tax ID": "12-345" }`

### B. Detailed Debug Traceability

To aid development and quality analysis, the parser will save artifacts when `DEBUG=True` or a new `docling_debug` flag is enabled.

-   **Raw JSON:** Save the complete Docling response to `scratch/docling/raw_{doc_id}_{timestamp}.json`.
-   **Raw Markdown:** Save the unsanitized Markdown to `scratch/docling/parsed_{doc_id}_{timestamp}.md`.
-   **Detailed Trace:** Log the "reasoning" for field matches (e.g., `"Matched 'Inv. No' to Custom Field 'Invoice Number' via synonym map"`).

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
