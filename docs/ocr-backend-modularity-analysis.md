# OCR Backend Modularity Analysis

**Date:** February 8, 2026
**Research Task:** Can `src/documents/parsers.py` changes be modularized?
**Result:** ✅ Architecture is already 90% modular - only minor refactoring needed

---

## Executive Summary

**Good News:** The existing paperless-ngx architecture already supports modular parser registration through Django's signal dispatcher pattern. The Docling and Ollama OCR backends are already implemented as separate Django apps (`paperless_docling` and `paperless_ollama`) that do NOT require modifications to core parser files for basic registration.

**However:** The current implementation in `parsers.py` contains OCR engine selection logic that could be further refactored for better modularity.

---

## How `src/documents/parsers.py` Currently Works

### Role in Document Processing Pipeline

`parsers.py` serves as the **central parser registry and dispatcher**:

1. **Parser Discovery**: Uses Django signals (`document_consumer_declaration`) to discover parsers from all installed apps
2. **MIME Type Matching**: Finds parsers that support specific MIME types
3. **Parser Selection**: Determines which parser to use based on weight/priority
4. **Base Classes**: Provides `DocumentParser` and `ImageDocumentParser` base classes

### Key Components (Lines 117-163)

```python
def get_parser_class_for_mime_type(mime_type: str) -> type[DocumentParser] | None:
    """
    Returns the best parser (by weight or OCR engine preference) for the given mimetype
    """
    options = []

    # 1. Collect all parsers that support this MIME type via signals
    for response in document_consumer_declaration.send(None):
        parser_declaration = response[1]
        if not parser_declaration:
            continue
        supported_mime_types = parser_declaration["mime_types"]
        if mime_type in supported_mime_types:
            options.append(parser_declaration)

    if not options:
        return None

    # 2. Priority function with OCR engine override
    def get_priority(declaration):
        parser_class = declaration["parser"]

        # Check Application Configuration for OCR engine setting
        from paperless.models import ApplicationConfiguration
        config = ApplicationConfiguration.objects.first()
        ocr_engine = (
            config.ocr_engine
            if config and config.ocr_engine
            else getattr(settings, "OCR_ENGINE", "tesseract")
        )

        # If selected OCR engine matches this parser, boost priority to 100
        if (
            ocr_engine == "docling" and parser_class.__name__ == "DoclingDocumentParser"
        ) or (
            ocr_engine == "ollama" and parser_class.__name__ == "OllamaDocumentParser"
        ):
            return 100
        else:
            return declaration["weight"]

    # 3. Return highest priority parser
    best_parser = sorted(options, key=get_priority, reverse=True)[0]
    return best_parser["parser"]
```

---

## What Changes Were Made to `parsers.py`

The current experimental branch contains these modifications:

### Added: OCR Engine Priority Logic (Lines 138-158)

```python
# Check Application Configuration first
from paperless.models import ApplicationConfiguration

config = ApplicationConfiguration.objects.first()
ocr_engine = (
    config.ocr_engine
    if config and config.ocr_engine
    else getattr(settings, "OCR_ENGINE", "tesseract")
)

if (
    ocr_engine == "docling" and parser_class.__name__ == "DoclingDocumentParser"
) or (
    ocr_engine == "ollama" and parser_class.__name__ == "OllamaDocumentParser"
):
    return 100
else:
    return declaration["weight"]
```

**This is the ONLY modification to core parsers.py** for OCR backend support.

---

## Existing Plugin Architecture

Paperless-NGX uses **Django's signal dispatcher pattern** for parser registration - this is already a modular, non-core-modifying approach.

### How Parser Apps Register Themselves

Each parser app follows this pattern:

#### 1. App Structure (Example: `paperless_docling/`)

```
paperless_docling/
├── __init__.py
├── apps.py              # App configuration, connects signal
├── signals.py           # Signal handler, returns parser declaration
├── parsers.py           # Actual parser implementation
└── models.py            # App-specific models (optional)
```

#### 2. App Configuration (`apps.py`)

```python
from django.apps import AppConfig
from paperless_docling.signals import docling_consumer_declaration

class PaperlessDoclingConfig(AppConfig):
    name = "paperless_docling"

    def ready(self):
        from documents.signals import document_consumer_declaration
        document_consumer_declaration.connect(docling_consumer_declaration)
        AppConfig.ready(self)
```

#### 3. Signal Handler (`signals.py`)

```python
def get_parser(*args, **kwargs):
    from paperless_docling.parsers import DoclingDocumentParser
    return DoclingDocumentParser(*args, **kwargs)

def docling_consumer_declaration(sender, **kwargs):
    from django.conf import settings
    from paperless.models import ApplicationConfiguration

    # Check if Docling should be active
    try:
        config = ApplicationConfiguration.objects.first()
        ocr_engine = (
            config.ocr_engine if config and config.ocr_engine else settings.OCR_ENGINE
        )
    except (ProgrammingError, OperationalError):
        ocr_engine = settings.OCR_ENGINE

    # Return None if not the selected engine (parser won't be registered)
    if not ocr_engine.startswith("docling"):
        return None

    # Return parser declaration
    return {
        "parser": get_parser,
        "weight": 3,
        "mime_types": ["application/pdf", "image/*"],
    }
```

#### 4. Signal Definition (`documents/signals/__init__.py`)

```python
from django.dispatch import Signal

document_consumer_declaration = Signal()
```

---

## Comparison: How Other Features Work

### Tika Integration (Fully Modular - No Core Modifications)

**Tika is the gold standard for modular integration:**

```python
# paperless_tika/apps.py
class PaperlessTikaConfig(AppConfig):
    name = "paperless_tika"

    def ready(self) -> None:
        from documents.signals import document_consumer_declaration

        # Only register if TIKA_ENABLED setting is True
        if settings.TIKA_ENABLED:
            document_consumer_declaration.connect(tika_consumer_declaration)
        AppConfig.ready(self)
```

```python
# paperless_tika/signals.py
def tika_consumer_declaration(sender, **kwargs):
    return {
        "parser": get_parser,
        "weight": 10,
        "mime_types": {
            "application/msword": ".doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            # ... more MIME types
        },
    }
```

**Key Difference:** Tika uses a simple `TIKA_ENABLED` boolean check, while OCR backends use a more complex selection mechanism.

### Tesseract Integration (Default Parser)

```python
# paperless_tesseract/signals.py
def tesseract_consumer_declaration(sender, **kwargs):
    return {
        "parser": get_parser,
        "weight": 0,  # Base weight
        "mime_types": {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            # ... more MIME types
        },
    }
```

---

## Could OCR Backend Logic Be More Modular?

### Current State: Mostly Modular

**✅ Already Working:**

-   Parser implementations are in separate apps (`paperless_docling/`, `paperless_ollama/`)
-   Parser registration uses Django signals (no core modifications needed)
-   Signal handlers can return `None` to skip registration

**⚠️ Partially Modular:**

-   OCR engine selection logic in `parsers.py:get_parser_class_for_mime_type()` uses hardcoded class name checks
-   The logic compares `parser_class.__name__` against strings like `"DoclingDocumentParser"`

---

## Recommended Refactoring Options

### Option A: Weight-Based Selection (Minimal Change) ⭐ RECOMMENDED

Modify signal handlers to use dynamic weights instead of hardcoded names:

```python
# paperless_docling/signals.py
def docling_consumer_declaration(sender, **kwargs):
    from django.conf import settings
    from paperless.models import ApplicationConfiguration

    try:
        config = ApplicationConfiguration.objects.first()
        ocr_engine = config.ocr_engine if config else settings.OCR_ENGINE
    except:
        ocr_engine = settings.OCR_ENGINE

    # Return None if not selected (parser not registered)
    if not ocr_engine.startswith("docling"):
        return None

    return {
        "parser": get_parser,
        "weight": 100,  # High weight when active
        "mime_types": ["application/pdf", "image/*"],
    }
```

Then simplify `parsers.py`:

```python
def get_priority(declaration):
    # Just use weight - signal handler already set it appropriately
    return declaration["weight"]
```

**Pros:**

-   Removes hardcoded class name checks
-   Simpler `parsers.py` logic
-   Each app controls its own priority when active

**Cons:**

-   Signal handlers must be called to determine weight (small overhead)

### Option B: Explicit Parser Registry (More Modular)

Create a dedicated OCR backend registry:

```python
# paperless/ocr_registry.py
from django.conf import settings

class OCRBackendRegistry:
    """Registry for OCR backend parsers"""

    _backends = {}

    @classmethod
    def register(cls, name, parser_factory, mime_types, default_weight=0):
        cls._backends[name] = {
            "parser": parser_factory,
            "mime_types": mime_types,
            "weight": default_weight,
        }

    @classmethod
    def get_active_backend(cls):
        from paperless.models import ApplicationConfiguration
        config = ApplicationConfiguration.objects.first()
        return config.ocr_engine if config else settings.OCR_ENGINE

    @classmethod
    def get_parser_for_mime_type(cls, mime_type):
        active_backend = cls.get_active_backend()

        # If active backend is registered, use it
        if active_backend in cls._backends:
            backend = cls._backends[active_backend]
            if mime_type in backend["mime_types"]:
                return backend["parser"]

        # Fall back to default behavior
        return None
```

Each app registers itself:

```python
# paperless_docling/apps.py
class PaperlessDoclingConfig(AppConfig):
    name = "paperless_docling"

    def ready(self):
        from paperless.ocr_registry import OCRBackendRegistry
        from paperless_docling.parsers import DoclingDocumentParser

        OCRBackendRegistry.register(
            name="docling",
            parser_factory=DoclingDocumentParser,
            mime_types=["application/pdf", "image/*"],
            default_weight=100,
        )
```

**Pros:**

-   Very explicit registration mechanism
-   Easy to extend with new backends
-   No signal overhead
-   Clear separation of concerns

**Cons:**

-   Requires new infrastructure
-   Apps must be loaded in correct order
-   More code to maintain

### Option C: Keep Current Approach (Document It)

The current approach is actually reasonable:

```python
# parsers.py - Current approach (documented)
def get_priority(declaration):
    parser_class = declaration["parser"]
    ocr_engine = get_ocr_engine_setting()

    # Priority boost for selected OCR engine
    # This allows multiple parsers to register, but selected one wins
    if ocr_engine == "docling" and parser_class.__name__ == "DoclingDocumentParser":
        return 100
    if ocr_engine == "ollama" and parser_class.__name__ == "OllamaDocumentParser":
        return 100

    return declaration["weight"]
```

**Pros:**

-   Works today
-   All OCR backends are already modular apps
-   Signal-based registration already in use
-   Only one small function needs modification for new backends

**Cons:**

-   Requires modifying `parsers.py` for each new OCR backend
-   Hardcoded class name strings are fragile (renaming breaks it)
-   Core file modification needed

---

## Pros/Cons Analysis

### Current Approach (Class Name Checks in parsers.py)

**Pros:**

-   ✅ Works immediately
-   ✅ All OCR backends are already modular apps
-   ✅ Signal-based registration already in use
-   ✅ Only one small function needs modification for new backends

**Cons:**

-   ❌ Requires modifying `parsers.py` for each new OCR backend
-   ❌ Hardcoded class name strings are fragile (renaming breaks it)
-   ❌ Core file modification needed

### Refactored Approach (Option A: Dynamic Weights)

**Pros:**

-   ✅ No core file modifications needed for new backends
-   ✅ Signal handlers control their own priority
-   ✅ Cleaner separation of concerns
-   ✅ Each app is self-contained

**Cons:**

-   ⚠️ Requires changes to existing signal handlers
-   ⚠️ Slight refactoring effort

### Refactored Approach (Option B: Registry Pattern)

**Pros:**

-   ✅ Most modular design
-   ✅ No core modifications for new backends
-   ✅ Explicit registration is clear
-   ✅ Easy to test and mock

**Cons:**

-   ⚠️ Most complex to implement
-   ⚠️ Requires new infrastructure
-   ⚠️ May be overkill for current use case

---

## Recommendation

### Immediate Action: Document Current Approach

The current implementation is **already 90% modular**. The only core file modification is the OCR engine priority logic in `get_parser_class_for_mime_type()`.

**For production use today:**

1. ✅ Keep the existing signal-based app structure
2. ✅ Document the class name check pattern
3. ✅ Add comments explaining how to add new backends

### Medium-Term: Implement Option A (Dynamic Weights)

**Recommended refactoring** for better modularity without major changes:

1. Modify signal handlers to return high weight (100) when their backend is selected
2. Simplify `parsers.py` to just use `declaration["weight"]`
3. Remove hardcoded class name checks

This requires:

-   Small change to `parsers.py` (remove class name checks)
-   Small changes to signal handlers (add weight logic)
-   **Result: Zero core modifications for future backends**

### Long-Term: Consider Option B (Registry)

If paperless-ngx plans to support many more OCR backends (5+), consider a formal registry pattern.

---

## Code Examples

### Example: Adding a New OCR Backend (Current Approach)

```python
# 1. Create new app: src/paperless_mycustomocr/
# 2. Implement parser (inherits from ImageDocumentParser)
# 3. Create signals.py:

def mycustomocr_consumer_declaration(sender, **kwargs):
    from django.conf import settings
    from paperless.models import ApplicationConfiguration

    try:
        config = ApplicationConfiguration.objects.first()
        ocr_engine = config.ocr_engine if config else settings.OCR_ENGINE
    except:
        ocr_engine = settings.OCR_ENGINE

    if ocr_engine != "mycustomocr":
        return None

    return {
        "parser": get_parser,
        "weight": 4,
        "mime_types": ["application/pdf", "image/*"],
    }

# 4. Create apps.py to connect signal
# 5. Add to settings.py INSTALLED_APPS (conditionally)
# 6. Modify parsers.py get_priority() to add:
#    if ocr_engine == "mycustomocr" and parser_class.__name__ == "MycustomocrDocumentParser":
#        return 100
```

### Example: Adding a New OCR Backend (Refactored Approach - Option A)

```python
# 1. Create new app: src/paperless_mycustomocr/
# 2. Implement parser
# 3. Create signals.py:

def mycustomocr_consumer_declaration(sender, **kwargs):
    from django.conf import settings
    from paperless.models import ApplicationConfiguration

    try:
        config = ApplicationConfiguration.objects.first()
        ocr_engine = config.ocr_engine if config else settings.OCR_ENGINE
    except:
        ocr_engine = settings.OCR_ENGINE

    if ocr_engine != "mycustomocr":
        return None

    return {
        "parser": get_parser,
        "weight": 100,  # High weight when active
        "mime_types": ["application/pdf", "image/*"],
    }

# 4. Create apps.py to connect signal
# 5. Add to settings.py INSTALLED_APPS
# 6. DONE! No parsers.py modification needed
```

---

## Conclusion

**The paperless-ngx codebase already has a modular plugin architecture for OCR backends.** The Docling and Ollama implementations are good examples of how to add new OCR backends without modifying core files - they use Django's signal dispatcher pattern effectively.

The **only** core file modification is a small function in `parsers.py` that checks the selected OCR engine and boosts the priority of the corresponding parser. This could be refactored to be more modular, but the current implementation is functional and maintainable.

**Bottom line:** The OCR broker architecture is already mostly modular. The question is whether to refactor the small priority-boosting logic in `parsers.py` to make it 100% modular, or document the current pattern for future backend developers.

---

## Appendix: File Locations

Key files mentioned in this analysis:

-   `/src/documents/parsers.py` - Core parser registry (lines 117-163 contain OCR logic)
-   `/src/documents/signals/__init__.py` - Signal definitions
-   `/src/paperless/settings.py` - App registration (lines 335-366 for INSTALLED_APPS)
-   `/src/paperless/models.py` - ApplicationConfiguration with ocr_engine field (line 409)
-   `/src/paperless_tesseract/` - Default OCR (Tesseract)
-   `/src/paperless_docling/` - Docling OCR backend (modular app)
-   `/src/paperless_ollama/` - Ollama OCR backend (modular app)
-   `/src/paperless_tika/` - Tika parser (modular app, good reference)
