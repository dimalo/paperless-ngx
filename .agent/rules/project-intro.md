---
trigger: always_on
---

# Paperless-ngx Agent Guidelines

Paperless-ngx is a Django-based document management system.

## Stack

- **Framework**: Django 5.2+ | Python 3.10+
- **Manager**: `uv`
- **Linting**: `ruff` (fmt/lint), `pre-commit`
- **Testing**: `pytest` (standard) or `manage.py test`

## Commands

### Setup & Quality

```bash
uv sync --all-groups --all-extras # Install all deps (every group/extra)
pre-commit run --all-files    # Run full linting suite
uv run ruff check --fix src/  # Fix lint errors
uv run ruff format src/       # Format code
uv run mypy                   # Type check
```

### Django

Run in `src/`: `uv run python manage.py <command>`

- `migrate`, `createsuperuser`, `collectstatic`, `check`

### Docker

- Build: `docker build -f Dockerfile -t paperless:local .`
- Compose: `docker/compose/docker-compose.{sqlite,postgres,mariadb}.yml`
- Tag: `PNGX_TAG_VERSION` for dev tags.

## OCR Modules

### Docling

External service for high-quality document conversion and OCR (PDF/Images).

### Ollama (Deepseek)

Local LLM-based OCR using Deepseek models via the Ollama API.

### Parser Logic

The system selects parsers (`DoclingDocumentParser` or `OllamaDocumentParser`) dynamically based on the `PAPERLESS_OCR_ENGINE` environment variable in `src/documents/parsers.py`.

## Development Standards

### Python Rules

- **Style**: Black/Ruff style (88 chars, double quotes).
- **Imports**: Absolute only. Sorted by Ruff (Stdlib > 3rd Party > Local).
- **Typing**: Mandatory modern type hints.
- **Models**: Use `ModelWithOwner` and `SoftDeleteModel` where applicable. Define `verbose_name` and `__str__`.

### Directories

- `src/`: Django backend
- `src-ui/`: Frontend (Prettier formatted)
- `tests/`: Module-local tests. Use **Factory Boy** (`tests/factories.py`) over fixtures.

### Best Practices

- **Security**: Use `pathvalidate` for file paths. Validate all inputs.
- **Perf**: Use `select_related`/`prefetch_related`. Async tasks via Celery.
