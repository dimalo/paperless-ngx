# Local Development Setup (Connected to K8s Services)

This document outlines the requirements and steps for running Paperless-NGX locally in development mode while connecting to Kubernetes services (PostgreSQL DB and Redis broker) for debugging and testing.

## Prerequisites

- **K8s Services**: Ensure shared PostgreSQL and Redis are deployed in `infrastructure/components/` and running in `homelab-system` namespace.
- **Ollama**: Running on macOS host at `http://localhost:11434` (pull `deepseek-ocr` model).
- **Python Environment**: Python 3.x, virtualenv or uv for dependencies.
- **Git**: Repository cloned with `paperless-ngx/` subrepo on `feature/docling-ollama-ocr-backends` branch.

## Setup Steps

1. **Navigate to Subrepo**:

   ```bash
   cd paperless-ngx/
   ```

2. **Install Dependencies**:

   ```bash
   pip install -r requirements.txt
   # Or with uv: uv sync --group dev
   ```

3. **Create .env File**:
   Create `.env` in `paperless-ngx/` root:

   ```
   PAPERLESS_DBHOST=localhost
   PAPERLESS_DBPORT=5432
   PAPERLESS_DBNAME=paperless_dev
   PAPERLESS_DBUSER=homelab
   PAPERLESS_DBPASS=homelab-secure-password
   PAPERLESS_REDIS=redis://localhost:6379
   PAPERLESS_OCR_ENGINE=ollama
   PAPERLESS_OLLAMA_BASE_URL=http://localhost:11434
   PAPERLESS_OLLAMA_MODELS=deepseek-ocr
   PAPERLESS_TIME_ZONE=Europe/Berlin
   PAPERLESS_SECRET_KEY=0292f1acc22e36ac28e8cd3d278e0ab6f02684e0470a7df64e678d0bfc2ae2fa
   ```

4. **Create Local Directories**:

   ```bash
   mkdir -p data media consume export
   ```

5. **Port-Forward K8s Services** (run in background/parallel):

   - PostgreSQL: `kubectl port-forward svc/postgresql 5432:5432 -n homelab-system &`
   - Redis: `kubectl port-forward svc/redis 6379:6379 -n homelab-system &`

6. **Initialize Database**:

   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py createsuperuser  # Optional, for admin access
   ```

7. **Run Locally**:
   ```bash
   python manage.py runserver 8000
   ```
   Access at `http://localhost:8000`.

## Testing and Debugging

- Upload test documents to `consume/` directory.
- Check logs for OCR/AI via console or `python manage.py djangolog`.
- Verify connections: DB via psql, Redis via redis-cli.

## Notes

- Volumes: Local dirs replace k8s PVCs; sync if needed.
- Security: Protect `.env`; don't commit secrets.
- Performance: Local run uses host resources; monitor Mac Studio (20% overhead).
- Fullstack: Build front-end separately if needed (`cd src-ui; ng build`).</content>
  <parameter name="filePath">paperless-ngx/local-dev-k8s.md
