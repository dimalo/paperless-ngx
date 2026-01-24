### PRD-7: Paperless-NGX Custom Enhancements

**Version**: 1.0
**Date**: January 20, 2026
**Author**: OpenCode Assistant
**Status**: Draft

#### Overview

This PRD outlines the setup and development of custom enhancements to Paperless-NGX, using the existing `paperless-ngx/` repo as a Git subrepo. Building on the active `feature/docling-ollama-ocr-backends` branch (which adds Docling and Ollama OCR backends for improved text extraction), we will add direct receipt processing features (e.g., field extraction and iCloud integration) and deploy a dev version to k8s with a cloned database to avoid production migrations. This eliminates the need for separate tools like paperless-gpt or ai subrepos.

#### Goals & Objectives

- **Primary Goal**: Enhance Paperless-NGX with custom receipt processing (extract amount/account/due date, create iCloud Calendar events and Reminders) using the new OCR backends.
- **Secondary Goals**:
  - Set up `paperless-ngx/` as a Git subrepo for development.
  - Deploy dev version to k8s (`homelab-dev` namespace, `paperless-dev.lima-0.lan` ingress).
  - Clone production PostgreSQL DB for dev testing without migrations.
  - Integrate with existing stack (Ollama for AI, k8s monitoring).

#### Requirements

##### Functional Requirements

1. **Receipt Processing Enhancements**:
   - Extend OCR backends (Docling/Ollama) with custom extraction logic for receipts (amount, account, due date).
   - Add iCloud integration: Use pyicloud to create Calendar events and Reminders on upload/categorization.
   - AI Categorization: Leverage Ollama for advanced doc type detection and auto-tagging.
2. **Subrepo and Development Workflow**:
   - Convert `paperless-ngx/` to Git submodule in the main repo.
   - CI/CD for building custom Docker images from the feature branch.
3. **Dev Deployment**:
   - K8s manifests in `apps/paperless-ngx-dev/` using Kustomize.
   - DB clone: Full PostgreSQL dump/restore from production to dev (isolated PVC).
   - Ingress with SSL; resource limits aligned with Mac Studio.

##### Non-Functional Requirements

1. **Resource Constraints**: Dev deployment <2Gi RAM, <500m CPU; no production impact.
2. **Security & Privacy**: Local-only iCloud API calls; K8s Secrets for credentials.
3. **Maintainability**: Subrepo for upstream merges; clear branching (e.g., `feature/receipt-icloud`).
4. **Compatibility**: Paperless-NGX 2.x (Django/Python); k8s 1.24+; PostgreSQL.

#### Technical Architecture

- **Subrepo Structure**: `apps/paperless-ngx/` as submodule (URL: custom repo based on upstream Paperless-NGX).
- **Code Changes**:
  - Modify `src/documents/` (e.g., `views.py`, `models.py`) for receipt extraction using Ollama API.
  - Add `src/documents/integrations/icloud.py` for Calendar/Reminder creation.
  - Leverage existing `feature/docling-ollama-ocr-backends` branch.
- **Deployment**: Separate from production (`homelab-apps`); dev namespace with cloned DB PVC.
- **DB Clone**: Script using `pg_dump`/`pg_restore`; automate in deployment.

#### Implementation Plan

1. **Subrepo Setup**: Add `paperless-ngx/` as submodule; push feature branch to custom repo.
2. **Code Development**: Implement receipt extraction and iCloud integration on the branch.
3. **DB Clone**: Create script for production DB dump and dev restore.
4. **Dev Deployment**: Build manifests; deploy with ingress.
5. **Testing**: Validate receipt processing and iCloud sync with sample docs.
6. **Integration**: Ensure compatibility with Dagster (PRD-6) for advanced workflows.

##### Dependencies

- Existing: PostgreSQL, Ollama, k8s infrastructure.
- New: pyicloud library, custom Docker registry.

#### Risks & Mitigations

- **DB Clone Issues**: Test restore process; use anonymized data if needed.
- **Upstream Conflicts**: Subrepo isolates changes; plan merges carefully.
- **iCloud API Limits**: Implement retries; monitor usage.
- **Resource Contention**: Dev namespace prevents production overlap.

#### Success Criteria

- Dev Paperless-NGX deployed at `paperless-dev.lima-0.lan`; receipt upload triggers iCloud event creation.
- OCR backends improved; DB clone functional without migrations.
- Subrepo active; code changes committed and tested.

This PRD builds on the explored changes (OCR backends, AI enhancements) for direct Paperless-NGX improvements. Deprecates paperless-ai; evaluates paperless-gpt.</content>
<parameter name="filePath">PRD-7.md
