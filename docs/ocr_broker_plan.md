# OCR Broker Implementation Plan (PR 1: Complete Foundation + Workflow Integration)

## Overview

This document outlines the plan for implementing an **OCR Broker** system with workflow integration. This system will replace the current hardcoded parser selection logic with a flexible, priority-based mechanism, allowing Paperless-ngx to dynamically choose between different OCR engines (Tesseract, Docling, Ollama, etc.) based on:

1. **Global Priority Configuration** (UI-configurable default)
2. **Workflow-based Overrides** (per-document routing based on filename, path, source, or mailrule)

## Architectural Understanding

### Workflow Timing: The Key Insight

Paperless has **two workflow trigger points** with different capabilities:

#### Phase 1: CONSUMPTION Workflows (Pre-Parse) ← OCR Engine Selection Goes Here

-   **Timing:** Runs BEFORE document parsing
-   **Location:** `WorkflowTriggerPlugin` in `src/documents/consumer.py:56-76`
-   **Can match on:** Filename patterns, path patterns, document source, mailrule
-   **Cannot match on:** Content, tags, correspondent (not extracted yet)
-   **Returns:** `DocumentMetadataOverrides` object that shapes the processing pipeline
-   **Perfect for:** Selecting which OCR engine to use based on input characteristics

#### Phase 2: DOCUMENT_ADDED/UPDATED Workflows (Post-Parse)

-   **Timing:** Runs AFTER document is saved to database
-   **Can match on:** Content, tags, correspondent, document_type, etc.
-   **Perfect for:** Content-based tagging, filing, notifications

### Why This Design is Ideal

Users naturally organize their inputs before processing:

-   Scan receipts to `/consume/receipts/` → Route to Ollama (vision model)
-   Email invoices arrive via mailrule → Route to Docling (high accuracy)
-   Quick scans from mobile → Route to Tesseract (fast, efficient)

This pre-parse routing is more practical than content-based routing because:

1. Filename/path patterns are predictable (`*invoice*.pdf`, `*receipt*.jpg`)
2. Users already organize inputs (folders, mail filters)
3. Source-based routing matches real-world workflows

---

### 1. Parser Metadata (Signal Update)

The `document_consumer_declaration` signal is used by apps to register their parsers. We need to add an optional `engine_id` to the metadata returned by these handlers.

-   **Files involved:** `src/documents/signals/__init__.py` (Documentation) and various signal handlers (e.g., `src/paperless_tesseract/signals.py`).
-   **Change:** Update the expected return dictionary format for handlers connected to `document_consumer_declaration`.
-   **New Field:** `engine_id` (Type: `str`, Optional).
    -   Example for Tesseract: `"engine_id": "tesseract"`
-   **Backward Compatibility:** If `engine_id` is missing, the broker should treat it as a generic parser with no specific engine association, relying purely on its `weight`.

---

### 2. Broker Algorithm (`get_parser_class_for_mime_type`)

The core selection logic resides in `src/documents/parsers.py`. You will modify `get_parser_class_for_mime_type` to implement the \"Broker\" logic with workflow override support.

**New Function Signature:**

```python
def get_parser_class_for_mime_type(
    mime_type: str,
    preferred_engine: str | None = None
) -> type[DocumentParser] | None:
```

**Step-by-step logic:**

1.  **Gather Declarations:** Call `document_consumer_declaration.send(None)` to get all registered parsers.
2.  **Filter by MIME type:** Keep only those parsers that support the document's `mime_type`.
3.  **Check for Workflow Override:** If `preferred_engine` is provided (from workflow):
    -   Find the parser with matching `engine_id`
    -   If found, return it immediately (workflow override has absolute priority)
    -   If not found (engine not installed), log a warning and continue to global priority
4.  **Fetch Global Priority List:** Retrieve the `OCR_ENGINE_PRIORITY` setting (from database `ApplicationConfiguration` or fallback to `settings.py`). Convert to list of strings (e.g., `["docling", "tesseract"]`).
5.  **Calculate Priority Scores:** For each available parser:
    -   If the parser has an `engine_id` that exists in the `OCR_ENGINE_PRIORITY` list, assign a priority score based on its position (earlier in list = higher score, use formula: `1000 - index`)
    -   If the `engine_id` is not in the list or is missing, use the parser's default `weight` (usually `0`)
6.  **Selection:** Sort the parsers by their calculated priority score (primary) and their original `weight` (secondary) in descending order. Return the top match.

---

### 3. Configuration Setup

New settings are required to store the engine priority order.

-   **`src/paperless/models.py` (`ApplicationConfiguration`):**
    -   Add `ocr_engine_priority = models.CharField(...)`.
    -   Store as a comma-separated string (e.g., `"docling,tesseract"`).
    -   Include a helpful `help_text` explaining that the first engine in the list has the highest priority.
-   **`src/paperless/settings.py`:**
    -   Add a default `OCR_ENGINE_PRIORITY = "tesseract"`.
    -   Ensure it can be overridden by an environment variable `PAPERLESS_OCR_ENGINE_PRIORITY`.

---

### 4. Impact Analysis (Tesseract Implementation)

This change is designed to be seamless:

-   **Existing Behavior:** Tesseract currently has a weight of `0`. In the new system, if no priority is set, it remains the default.
-   **Migration:** You will update `src/paperless_tesseract/signals.py` to include `"engine_id": "tesseract"` in the return dict.
-   **Failure Modes:** If a user specifies a priority list like `docling,tesseract` but Docling is not installed/registered, the broker will automatically pick Tesseract as the next available match in the list.

---

### 5. Reference Hunks & Adaptation

The current logic in the `feature/docling-ollama-ocr-backends` branch contains a hardcoded version of this broker. Use it as a reference but **do not copy it exactly**.

**Reference Location:** `src/documents/parsers.py` (Lines 137-162 in the feature branch).

**How to rewrite it:**

-   **Current Hardcoded Logic:**
    ```python
    if (ocr_engine == "docling" and parser_class.__name__ == "DoclingDocumentParser"):
        return 100
    ```
-   **Your "Broker" Adaptation:**
    Replace the `if/else` block with a lookup in your `priority_list`.
    ```python
    # Logic Sketch:
    engine_id = declaration.get("engine_id")
    if engine_id in priority_list:
        # Assign a high score based on index
        return 1000 - priority_list.index(engine_id)
    return declaration.get("weight", 0)
    ```

---

### Summary of Files to Modify (PR 1: Complete Implementation)

#### Backend (Python/Django)

1.  **`src/paperless/models.py`** - Add `ocr_engine_priority` field to `ApplicationConfiguration`
2.  **`src/paperless/settings.py`** - Add `OCR_ENGINE_PRIORITY` default setting with env var support
3.  **`src/paperless_tesseract/signals.py`** - Add `"engine_id": "tesseract"` to signal handler
4.  **`src/documents/parsers.py`** - Implement broker algorithm with `preferred_engine` parameter
5.  **`src/documents/data_models.py`** - Add `ocr_engine` field to `DocumentMetadataOverrides`
6.  **`src/documents/models.py`** - Add `assign_ocr_engine` field to `WorkflowAction`
7.  **`src/documents/workflows/mutations.py`** - Handle OCR engine assignment in overrides
8.  **`src/documents/consumer.py`** - Pass `preferred_engine` from metadata to broker

#### Frontend (Angular/TypeScript)

9.  **`src-ui/src/app/data/paperless-config.ts`** - Define `ocr_engine_priority` config field
10. **`src-ui/src/app/components/settings/config/config.component.html`** - Add drag-and-drop UI for global priority
11. **`src-ui/src/app/data/workflow-action.ts`** - Add `assign_ocr_engine` to WorkflowAction interface
12. **`src-ui/src/app/components/manage/workflow-edit-dialog/`** - Add OCR engine dropdown to assignment UI

#### Database Migration

13. **Auto-generated migration** - Two new fields: `ApplicationConfiguration.ocr_engine_priority` and `WorkflowAction.assign_ocr_engine`

---

### 6. Workflow Integration (Active Pipeline Steering) — INCLUDED IN PR 1

**Why Include This:** Workflows run BEFORE parsing during the CONSUMPTION phase, making them the perfect mechanism for OCR engine selection. They can match on filename, path, source, and mailrule—exactly the characteristics users use to organize their documents.

**Real-World Use Cases:**

-   "Process files matching `*invoice*.pdf` with Docling for high accuracy"
-   "Use Tesseract for Consume Folder (fast), Ollama for Mail Fetch (accurate)"
-   "Route receipts from `/consume/receipts/*` to vision-capable Ollama model"

#### Implementation Steps:

##### A. Extend DocumentMetadataOverrides

**File:** `src/documents/data_models.py`

Add new field to the `DocumentMetadataOverrides` dataclass (around line 33):

```python
ocr_engine: str | None = None
```

Update the `update()` method to handle the new field (around line 54):

```python
if other.ocr_engine is not None:
    self.ocr_engine = other.ocr_engine
```

##### B. Add Workflow Assignment Field

**File:** `src/documents/models.py`

Add new field to `WorkflowAction` model (around line 1550, after existing assignment fields):

```python
assign_ocr_engine = models.CharField(
    verbose_name=_("assign OCR engine"),
    null=True,
    blank=True,
    max_length=32,
    help_text=_(
        "Override the OCR engine for this document. "
        "Available engines: tesseract, docling, ollama (if installed)."
    ),
)
```

**Note:** We do NOT need a new `WorkflowActionType`. OCR engine assignment is part of the existing `ASSIGNMENT` action type, just like tags, correspondent, etc.

##### C. Update Workflow Mutations

**File:** `src/documents/workflows/mutations.py`

Add new function `apply_assignment_to_overrides` (if it doesn't exist) or update existing one to handle OCR engine assignment (around line 120):

```python
def apply_assignment_to_overrides(
    action: WorkflowAction,
    overrides: DocumentMetadataOverrides,
):
    """
    Apply assignment actions to DocumentMetadataOverrides (pre-consumption).
    """
    # ... existing assignments (tags, correspondent, etc.) ...

    if action.assign_ocr_engine:
        overrides.ocr_engine = action.assign_ocr_engine
```

##### D. Update Consumer to Pass Preferred Engine

**File:** `src/documents/consumer.py`

Modify the `ConsumerPlugin.run()` method to extract the OCR engine from metadata overrides and pass it to the broker (around line 343):

**Current code:**

```python
parser_class: type[DocumentParser] | None = get_parser_class_for_mime_type(
    mime_type,
)
```

**New code:**

```python
parser_class: type[DocumentParser] | None = get_parser_class_for_mime_type(
    mime_type,
    preferred_engine=self.metadata.ocr_engine,  # Pass workflow override
)
```

##### E. Update Broker Function Signature

**File:** `src/documents/parsers.py`

This is already covered in Section 2 above. The broker now accepts `preferred_engine` parameter and handles it as the highest priority override.

#### Migration Required

-   **Database:** New field `assign_ocr_engine` in `WorkflowAction` table
-   **Migration File:** Auto-generated via `python manage.py makemigrations`
-   **Backward Compatibility:** Fully compatible (new field is nullable)

---

### 7. Future Extensibility: Advanced Routing (PR 2+)

The foundation is designed to support future enhancements without breaking changes:

-   **Per-MIME Type Priorities:** Different engine priorities for `application/pdf` vs `image/png`
-   **Content-based Re-OCR:** Trigger workflows on DOCUMENT_ADDED to detect content patterns and re-process with different engine
-   **Performance Monitoring:** Track engine performance/cost metrics to auto-adjust priorities
-   **Fallback Chains:** Automatic retry with different engine if first attempt fails

**Note on \"Redo OCR\":**
Currently, re-processing tasks do not trigger workflows. A future PR should explore:

1. Enabling workflow evaluation during re-processing
2. Adding a "Re-OCR with different engine" bulk action
3. Allowing DOCUMENT_ADDED workflows to trigger OCR changes for existing documents

---

### 8. UI/UX Implementation Details

To ensure the features feel native to Paperless-ngx, use the following UI patterns:

**A. Global Engine Priority (OCR Settings)**

-   **Location:** OCR Settings tab in Application Configuration
-   **Component:** Use the `pngx-input-drag-drop-select` component
-   **Behavior:** Allows users to visually rank engines by dragging items
-   **Data Format:** Frontend serializes to comma-separated string (e.g., `"docling,tesseract,ollama"`)
-   **Available Options:** Dynamically populated based on installed engines (detect via parser registration)

**B. Workflow OCR Engine Assignment**

-   **Location:** Workflow Edit Dialog → Assignment section
-   **Component:** Standard `pngx-input-select` dropdown (same pattern as Correspondent, Document Type, etc.)
-   **Label:** "OCR Engine" or "Assign OCR Engine"
-   **Options:** Dropdown with available engines: `[{ id: "tesseract", name: "Tesseract" }, { id: "docling", name: "Docling" }, ...]`
-   **Placement:** Add after "Storage Path" assignment, before "Owner" assignment
-   **Behavior:** Optional field (blank = use global priority)

**C. Settings Organization**

-   **OCR Tab:** Keep for output parameters (PDF/A, DPI, rotation, cleaning) + new global priority setting
-   **AI Settings Tab:** For future engine-specific configs (Docling endpoint, Ollama model, etc.)
-   **Rationale:** OCR engine priority is a core OCR setting, engine-specific tuning is advanced/AI-related

**D. User Guidance**

-   **Help Text Examples:**
    -   Global Priority: "Drag to reorder OCR engines by preference. Paperless will use the first available engine for each document."
    -   Workflow Assignment: "Override the global OCR engine priority for documents matching this workflow. Leave blank to use global settings."

**E. Error Handling**

-   If workflow requests unavailable engine: Log warning, fall back to global priority
-   If global priority lists unavailable engine: Ignore it, use next available
-   If no engines available: Show clear error message during consumption

---

## PR 1 Deliverables: What Users Get

### For All Users (Global Priority)

✅ **Configurable OCR Engine Priority**

-   Set default engine preference in UI (Settings → OCR)
-   Drag-and-drop interface for easy ranking
-   Automatic fallback if preferred engine unavailable
-   Works immediately with existing consume folder, API uploads, mail fetch

### For Power Users (Workflow Integration)

✅ **Pattern-Based OCR Routing**

-   Route invoices (`*invoice*.pdf`) to Docling for high accuracy
-   Route receipts (`/consume/receipts/*`) to Ollama vision models
-   Use Tesseract for quick scans, Docling for important mail
-   Combine with existing workflow features (tagging, filing, notifications)

### For Administrators

✅ **Flexible Deployment Options**

-   Install only the engines you need (Tesseract-only, Tesseract+Docling, etc.)
-   Graceful degradation if engines unavailable
-   Environment variable support for priority configuration
-   No breaking changes to existing installations

### For Future PRs

✅ **Extensible Foundation**

-   Engine registry system ready for new backends
-   Metadata override pattern established
-   UI patterns proven and reusable
-   Clear path to content-based routing, per-MIME priorities, performance monitoring

---

## Testing Strategy

### Unit Tests Required

1. **Broker Logic** (`test_parsers.py`)

    - Test priority scoring algorithm
    - Test workflow override precedence
    - Test fallback behavior for missing engines
    - Test backward compatibility (parsers without `engine_id`)

2. **Workflow Integration** (`test_workflows.py`)

    - Test OCR engine assignment in CONSUMPTION workflows
    - Test metadata override propagation
    - Test interaction with other workflow assignments

3. **Configuration** (`test_models.py`)
    - Test priority list parsing (comma-separated string)
    - Test environment variable override
    - Test migration compatibility

### Integration Tests

1. **End-to-End Consumption**

    - Upload document → Workflow matches → Correct engine selected
    - Test filename pattern matching → OCR engine override
    - Test source-based routing (ConsumeFolder vs MailFetch)

2. **UI Testing**
    - Drag-and-drop priority reordering
    - Workflow dialog shows OCR engine dropdown
    - Settings save/load correctly

### Manual Testing Scenarios

1. Fresh install (Tesseract only) → Verify default behavior unchanged
2. Add Docling → Set priority → Verify Docling used
3. Create workflow with engine override → Verify precedence
4. Remove engine from system → Verify graceful fallback
5. Invalid priority config → Verify error handling

---

## Implementation Order (Recommended)

### Phase 1: Core Foundation (Backend)

1. Add settings (`models.py`, `settings.py`)
2. Update Tesseract signal handler (`signals.py`)
3. Implement broker algorithm (`parsers.py`)
4. Write unit tests for broker logic

### Phase 2: Workflow Integration (Backend)

5. Extend `DocumentMetadataOverrides` (`data_models.py`)
6. Add `assign_ocr_engine` field (`models.py`)
7. Update workflow mutations (`mutations.py`)
8. Update consumer to pass preferred engine (`consumer.py`)
9. Write workflow integration tests
10. Generate and test database migration

### Phase 3: Frontend (UI)

11. Add config field definition (`paperless-config.ts`)
12. Implement global priority UI (`config.component.html`)
13. Update workflow action interface (`workflow-action.ts`)
14. Add OCR engine dropdown to workflow dialog
15. Test UI interactions

### Phase 4: Integration & Documentation

16. End-to-end testing
17. Update user documentation
18. Update developer documentation (signal handler format)
19. Prepare PR description with examples

---

## Success Criteria

✅ **Backward Compatibility:** Existing installations work without changes
✅ **Zero Configuration:** Default behavior unchanged (Tesseract priority)
✅ **User Value:** Users can prioritize Docling/Ollama globally in 30 seconds
✅ **Power User Value:** Admins can route by pattern/source in 2 minutes
✅ **Developer Experience:** Clear extension point for new engines
✅ **Code Quality:** >90% test coverage, no performance regression
✅ **Documentation:** Clear migration guide for users of feature branch

---

## Notes for Implementation

**Critical Design Decisions:**

1. **Priority Scoring:** Use `1000 - index` to ensure priority always beats weight
2. **Workflow Precedence:** `preferred_engine` overrides global priority (absolute)
3. **Fallback Strategy:** Invalid engine → Log warning + use next priority, not fail
4. **Field Type:** `assign_ocr_engine` is CharField (not ForeignKey) to avoid coupling to engine availability

**Potential Pitfalls:**

-   Don't forget to update `apply_assignment_to_overrides` AND `apply_assignment_to_document` (two codepaths)
-   Frontend must handle optional/nullable `assign_ocr_engine` gracefully
-   Migration must be compatible with existing workflow actions (null default)
-   Cache invalidation: `@lru_cache` on `get_parser_class_for_mime_type` may need clearing if priority changes

**Questions to Resolve During Implementation:**

1. Should invalid `assign_ocr_engine` value fail workflow or just warn?
2. Should UI show only installed engines or all possible engines?
3. Should we add logging for which engine was selected and why (for debugging)?
4. Should the workflow action validate `assign_ocr_engine` against available engines at save time?
