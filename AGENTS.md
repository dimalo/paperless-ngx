# Paperless-ngx Agent Guidelines

This file contains guidelines and commands for AI agents working on the Paperless-ngx codebase. Paperless-ngx is a Django-based document management system written in Python.

## Project Overview

- **Framework**: Django 5.2+
- **Language**: Python 3.10+
- **Package Manager**: uv
- **Testing**: pytest with Django
- **Linting**: ruff
- **Formatting**: ruff-format
- **Code Quality**: pre-commit hooks

## Development Commands

### Package Management
```bash
# Install all dependencies (including dev dependencies)
uv sync --group dev

# Install only production dependencies
uv sync

# Install with specific optional dependencies
uv sync --group postgres  # or --group mariadb
```

### Testing

#### Run All Tests
```bash
# Run all tests with coverage
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run tests in parallel (auto-detect CPU count)
uv run pytest --numprocesses=auto
```

#### Run Specific Tests

```bash
# Run tests for a specific module
uv run pytest src/documents/tests/test_models.py

# Run tests for a specific class
uv run pytest src/documents/tests/test_models.py::DocumentTestCase

# Run a single test method
uv run pytest src/documents/tests/test_models.py::DocumentTestCase::test_correspondent_deletion_does_not_cascade

# Run tests matching a pattern
uv run pytest -k "test_correspondent"

# Run tests with coverage for specific files
uv run pytest --cov=documents.models src/documents/tests/test_models.py
```

#### Test Configuration
- Tests are configured in `pyproject.toml` under `[tool.pytest.ini_options]`
- Coverage reporting: HTML and XML formats
- Test paths: `src/documents/tests/`, `src/paperless*/tests/`
- Django settings module: `paperless.settings`

### Linting and Code Quality

#### Run All Linting
```bash
# Run pre-commit on all files (includes all linting/formatting)
pre-commit run --all-files

# Run only on changed files
pre-commit run
```

#### Individual Linters

```bash
# Ruff linting and fixes
uv run ruff check src/
uv run ruff check --fix src/

# Ruff formatting
uv run ruff format src/

# Type checking (mypy)
uv run mypy

# Import sorting (isort via ruff)
uv run ruff check --select I src/
```

### Django Management Commands

```bash
# Run Django management commands
cd src && uv run python manage.py <command>

# Common commands:
uv run python manage.py migrate                    # Database migrations
uv run python manage.py createsuperuser           # Create admin user
uv run python manage.py collectstatic             # Collect static files
uv run python manage.py check                      # System checks

# Testing with Django test runner (alternative to pytest)
uv run python manage.py test
```

### Docker Building

#### Build Local Development Container
```bash
# Build the Paperless-ngx Docker container locally
docker build --file Dockerfile --tag paperless:local .

# For production builds (uses buildx with cross-platform support)
docker buildx build --platform linux/amd64,linux/arm64 --file Dockerfile --tag paperless:latest .
```

#### Docker Compose Environments
The project includes multiple docker-compose configurations for different database setups:
- `docker/compose/docker-compose.sqlite.yml` - SQLite database
- `docker/compose/docker-compose.postgres.yml` - PostgreSQL database
- `docker/compose/docker-compose.mariadb.yml` - MariaDB database
- Add `-tika.yml` suffix for versions with Tika OCR integration

#### Build Arguments
- `PNGX_TAG_VERSION`: Version tag for development builds (dev, beta, feature branches)

### OCR Backend Setup

#### Docling Backend
Paperless-ngx supports Docling as an OCR backend via docling-serve API service.

**Setup:**
1. Run docling-serve in Docker:
   ```bash
   docker run --name docling-serve -p 5001:5001 ds4sd/docling-serve:latest
   ```
2. Configure environment variables:
   ```bash
   export PAPERLESS_OCR_ENGINE=docling
   export PAPERLESS_DOCLING_ENDPOINT=http://localhost:5001
   export PAPERLESS_DOCLING_TIMEOUT=30
   export PAPERLESS_DOCLING_FORCE_OCR=false
   export PAPERLESS_DOCLING_LANGUAGE=eng
   ```

**Settings:**
- `PAPERLESS_DOCLING_ENDPOINT`: URL of the docling-serve instance (default: http://localhost:5001)
- `PAPERLESS_DOCLING_TIMEOUT`: Request timeout in seconds (default: 30)
- `PAPERLESS_DOCLING_FORCE_OCR`: Force OCR even on documents with existing text (default: false)
- `PAPERLESS_DOCLING_LANGUAGE`: OCR language for text recognition (default: eng)

**API Details:**
- Uses `/v1/convert/file` for sync processing
- Uses `/v1/convert/file/async` with polling for large files (>10MB)
- Supports PDF and image MIME types
- Extracts `text_content` from JSON response

#### Ollama Backend
Paperless-ngx supports Ollama as an OCR backend using the deepseek-ocr model.

**Setup:**
1. Install Ollama:
   ```bash
   # On Linux/macOS
   curl -fsSL https://ollama.ai/install.sh | sh

   # Or download from https://ollama.ai/download
   ```
2. Pull the deepseek-ocr model:
   ```bash
   ollama pull deepseek-ocr
   ```
3. Start Ollama service:
   ```bash
   ollama serve
   ```
4. Configure environment variables:
   ```bash
   export PAPERLESS_OCR_ENGINE=ollama
   export PAPERLESS_OLLAMA_ENDPOINT=http://localhost:11434
   export PAPERLESS_OLLAMA_MODEL=deepseek-ocr
   export PAPERLESS_OLLAMA_TIMEOUT=30
   export PAPERLESS_OLLAMA_PROMPT_TEMPLATE=""
   ```

**Settings:**
- `PAPERLESS_OLLAMA_ENDPOINT`: URL of the Ollama instance (default: http://localhost:11434)
- `PAPERLESS_OLLAMA_MODEL`: Model name (default: deepseek-ocr)
- `PAPERLESS_OLLAMA_TIMEOUT`: Request timeout in seconds (default: 30)
- `PAPERLESS_OLLAMA_PROMPT_TEMPLATE`: Custom prompt template (default: "")

**API Details:**
- Uses `POST /api/chat` endpoint
- Sends base64 encoded images in messages with user content
- Supports image and PDF MIME types (PDFs converted to images per page)
- Extracts `content` from message response

#### Parser Selection Logic
The `get_parser_class_for_mime_type()` function in `src/documents/parsers.py` selects the appropriate parser based on the `PAPERLESS_OCR_ENGINE` setting:

- If `PAPERLESS_OCR_ENGINE` is set to `docling`, prioritizes `DoclingDocumentParser`.
- If `PAPERLESS_OCR_ENGINE` is set to `ollama`, prioritizes `OllamaDocumentParser`.
- Otherwise, falls back to the parser with the highest weight.

This ensures that when a specific OCR backend is configured, it is used for supported MIME types.

## Code Style Guidelines

### Python Code Style

#### General Rules
- **Line Length**: 88 characters (ruff default)
- **Indentation**: 4 spaces
- **Imports**: Use absolute imports, sorted with ruff
- **Quotes**: Double quotes preferred for strings
- **Trailing Commas**: Required in multi-line structures
- **Docstrings**: Use triple double quotes
- **Type Hints**: Required for new code, use modern typing syntax

#### Import Organization
```python
# Standard library imports
import os
import sys
from pathlib import Path
from typing import List, Optional

# Third-party imports
import django
from django.db import models
import requests

# Local imports (alphabetically sorted)
from documents.models import Document
from documents.utils import process_file
```

#### Class and Function Definitions
```python
class DocumentModel(models.Model):
    """Document model for storing scanned documents."""

    title = models.CharField(
        max_length=255,
        help_text="Document title"
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
        verbose_name = "document"

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        """Custom save method with validation."""
        self.full_clean()
        super().save(*args, **kwargs)
```

#### Django Model Patterns
- Use `ModelWithOwner` for user-owned models
- Implement proper `__str__` methods
- Use verbose names for admin interface
- Add database constraints where appropriate
- Use soft deletes with `SoftDeleteModel` when needed

#### Error Handling
```python
try:
    document = Document.objects.get(pk=document_id)
except Document.DoesNotExist:
    raise Http404("Document not found")
except ValidationError as e:
    logger.error(f"Validation error for document {document_id}: {e}")
    return HttpResponseBadRequest("Invalid document data")
```

### JavaScript/TypeScript Style (Frontend)
- Follow Prettier formatting (configured in pre-commit)
- Use ES6+ syntax
- Consistent quote style (configured in Prettier)
- Import organization with prettier-plugin-organize-imports

### File Structure
- **Python**: `src/` directory
- **Frontend**: `src-ui/` directory (separate project)
- **Tests**: `tests/` subdirectories in each module
- **Templates**: `templates/` directories following Django conventions
- **Static Files**: `static/` directories

### Naming Conventions

#### Python
- **Classes**: PascalCase (e.g., `DocumentProcessor`)
- **Functions/Methods**: snake_case (e.g., `process_document`)
- **Constants**: UPPER_CASE (e.g., `MAX_FILE_SIZE`)
- **Variables**: snake_case (e.g., `document_title`)
- **Modules**: snake_case (e.g., `document_utils.py`)

#### Django Specific
- **Models**: Singular nouns (e.g., `Document`, not `Documents`)
- **Model Fields**: snake_case (e.g., `created_at`, `is_active`)
- **URLs**: kebab-case in patterns (e.g., `document-detail`)
- **Template Names**: snake_case (e.g., `document_list.html`)

#### Database
- **Table Names**: Django auto-generates (appname_modelname)
- **Column Names**: snake_case
- **Indexes**: descriptive names with `_idx` suffix

### Testing Patterns

#### Unit Tests
```python
from django.test import TestCase
from documents.tests.factories import DocumentFactory

class DocumentModelTest(TestCase):
    def test_document_creation(self):
        """Test basic document creation."""
        document = DocumentFactory.create()
        self.assertIsNotNone(document.pk)
        self.assertEqual(document.title, "Test Document")
```

#### Factory Usage
- Use Factory Boy factories in `tests/factories.py`
- Factories provide consistent test data
- Override specific attributes as needed

#### Test File Organization
- Tests mirror source structure: `src/app/tests/test_feature.py`
- Test classes inherit from `TestCase`
- Test methods start with `test_`
- Use descriptive method names

### Security Best Practices

#### Django Security
- Use Django's built-in authentication
- Validate all user inputs
- Use `get_object_or_404()` for database queries
- Implement proper permission checks
- Use HTTPS in production

#### File Handling
- Validate file types and sizes
- Use safe file paths (pathvalidate library)
- Avoid directory traversal attacks
- Clean up temporary files

#### Data Protection
- Implement audit logging where sensitive
- Use soft deletes for user data
- Encrypt sensitive stored data
- Follow GDPR/data protection principles

### Git Workflow

#### Commit Messages
- Use imperative mood: "Add feature" not "Added feature"
- Start with capital letter
- Keep first line under 50 characters
- Add detailed description for complex changes

#### Branching
- Feature branches: `feature/description`
- Bug fixes: `fix/issue-description`
- Hotfixes: `hotfix/critical-issue`

### Performance Considerations

#### Database Queries
- Use `select_related()` and `prefetch_related()` for joins
- Implement proper indexing
- Use Django's caching framework
- Avoid N+1 query problems

#### File Processing
- Process files asynchronously with Celery
- Use streaming for large file downloads
- Implement proper cleanup of temporary files
- Cache expensive operations

### Internationalization (i18n)
- Use Django's `gettext_lazy` for model strings
- Mark user-facing strings with `_()`
- Use `ugettext_lazy` for plurals
- Follow Django i18n best practices

## Pre-commit Hooks

The following hooks run automatically:
- `ruff-check`: Linting and import sorting
- `ruff-format`: Code formatting
- `pyproject-fmt`: pyproject.toml formatting
- `prettier`: Frontend formatting
- `codespell`: Spell checking
- `hadolint`: Dockerfile linting
- `shellcheck`: Shell script checking

## CI/CD Pipeline

### Backend Tests
- Runs on Python 3.10, 3.11, 3.12
- Includes coverage reporting
- Uses Docker Compose for test services
- Parallel test execution

### Linting
- Pre-commit checks on all files
- Runs on every push and PR
- Includes all configured hooks

## Environment Setup

### Development Environment
```bash
# Clone repository
git clone https://github.com/paperless-ngx/paperless-ngx.git
cd paperless-ngx

# Install dependencies
uv sync --group dev

# Set up environment variables
cp paperless.conf.example paperless.conf
# Edit paperless.conf with your settings

# Run database migrations
cd src && uv run python manage.py migrate

# Create superuser
uv run python manage.py createsuperuser

# Run development server
uv run python manage.py runserver
```

### Testing Environment
```bash
# Install test dependencies
uv sync --group testing

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov
```

## Troubleshooting

### Common Issues
- **Import errors**: Ensure you're in the correct directory (`src/` for Django commands)
- **Database connection**: Check Docker services are running for tests
- **Permission errors**: Use proper file permissions for document storage
- **Memory issues**: Large documents may require increased limits

### Debugging
- Use Django Debug Toolbar in development
- Enable SQL query logging: `LOGGING['loggers']['django.db.backends'] = {'level': 'DEBUG'}`
- Use `pdb` or `ipdb` for interactive debugging
- Check logs in `src/paperless.log`

## Resources
- [Django Documentation](https://docs.djangoproject.com/)
- [Paperless-ngx Docs](https://docs.paperless-ngx.com/)
- [Ruff Rules](https://docs.astral.sh/ruff/rules/)
- [uv Documentation](https://docs.astral.sh/uv/)