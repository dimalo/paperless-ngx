---
trigger: glob
description: Use these rules when you are testing python modules with pytest
globs: **/*test*.py
---

## When Testing

- run uv run pytest
- use manage.py if needed
- dont use xdist
- always run only a small subset of tests
- always run with coverage and missed statements

### Example

uv run pytest -o "addopts=" -o "numprocesses=0" src/paperless_ai/tests/test_embedding.py -k test_get_embedding_model_ollama --cov=src/paperless_ai --cov-report=term-missing

### Testing Details

#### Run All Tests

```bash
# Run all tests with coverage
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run tests in parallel (auto-detect CPU count with pytest-xdist)
uv run pytest -n auto
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

# Run multiple test files efficiently (avoids excessive process spawning)
uv run pytest src/documents/tests/test_models.py src/documents/tests/test_views.py

# If running separate commands, disable parallelism to avoid excessive processes
uv run pytest -n 1 src/documents/tests/test_models.py
```

#### Test Configuration

- Tests are configured in `pyproject.toml` under `[tool.pytest.ini_options]`
- Coverage reporting: HTML and XML formats
- Test paths: `src/documents/tests/`, `src/paperless*/tests/`
- Django settings module: `paperless.settings`
