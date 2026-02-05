import re
import time
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache

from documents.parsers import DocumentParser
from documents.parsers import ParseError
from documents.parsers import make_thumbnail_from_pdf
from documents.parsers import run_convert
from paperless.config import DoclingConfig
from paperless_docling.models import DoclingServerResult
from paperless_docling.models import ServerDocumentResponse


class DoclingDocumentParser(DocumentParser):
    """
    This parser uses Docling (local or server) to parse documents and extract text.
    """

    logging_name = "paperless.parsing.docling"

    def get_settings(self) -> DoclingConfig:
        """
        This parser uses the Docling configuration settings to parse documents
        """
        return DoclingConfig()

    def get_thumbnail(self, document_path: Path, mime_type, file_name=None) -> Path:
        # Use the original or archive if available
        return make_thumbnail_from_pdf(
            self.archive_path or document_path,
            self.tempdir,
            self.logging_group,
        )

    def is_image(self, mime_type: str) -> bool:
        return mime_type in [
            "image/png",
            "image/jpeg",
            "image/tiff",
            "image/bmp",
            "image/gif",
            "image/webp",
        ]

    def preprocess_image(self, input_file: Path) -> Path:
        """
        Prepare image for OCR using standard Paperless-ngx convert parameters.
        """
        output_file = self.tempdir / "preprocessed.png"
        run_convert(
            input_file=input_file,
            output_file=output_file,
            density=300,
            scale="2000x2000>",
            alpha="off",
            auto_orient=True,
            logging_group=self.logging_group,
        )
        return output_file

    def _save_debug_artifacts(self, response: DoclingServerResult) -> None:
        """
        Save raw Docling output for debugging/analysis if DEBUG is active.
        """
        if not getattr(settings, "DEBUG", False):
            return

        try:
            debug_dir = settings.SCRATCH_DIR / "docling"
            debug_dir.mkdir(parents=True, exist_ok=True)

            # 1. Raw JSON
            json_file = debug_dir / f"docling_{self.logging_group}_raw.json"
            json_file.write_text(response.model_dump_json(indent=2))

            # 2. Raw Markdown (before sanitization)
            if response.document.md_content:
                md_file = debug_dir / f"docling_{self.logging_group}_raw.md"
                md_file.write_text(response.document.md_content)

            self.log.debug(f"Saved Docling debug artifacts to {debug_dir}")
        except Exception as e:
            self.log.warning(f"Failed to save Docling debug artifacts: {e}")

    def _extract_metadata(self, response: DoclingServerResult) -> dict:
        """
        Extract key-value pairs and semantic labels from Docling result.
        Returns a dict compatible with Paperless-ngx's metadata consumption.
        """
        metadata = {
            "docling_key_value": {},
            "docling_labels": set(),
        }

        # 1. Key-Value Extraction
        if response.document.json_content:
            doc = response.document.json_content
            for item in doc.key_value_items:
                if item.key and item.value:
                    metadata["docling_key_value"][item.key] = item.value

        # 2. Semantic Labels
        if response.document.json_content:
            doc = response.document.json_content
            if doc.tables:
                metadata["docling_labels"].add("TABLE")
            if doc.headings:
                metadata["docling_labels"].add("HEADING")

            # Deep check for special labels in texts
            for text_item in doc.texts:
                if text_item.label in ["FORMULA", "HANDWRITTEN", "SIGNATURE"]:
                    metadata["docling_labels"].add(text_item.label)

        # Log findings for discovery (non-distracting)
        if metadata["docling_key_value"]:
            self.log.info(
                f"Docling found metadata: {list(metadata['docling_key_value'].keys())}",
            )
        if metadata["docling_labels"]:
            self.log.info(
                f"Docling detected features: {list(metadata['docling_labels'])}",
            )

        return metadata

    def _convert_server(self, file_path: Path) -> DoclingServerResult:
        """
        Convert file using Docling-serve using the async task pipeline.
        """
        if not self.settings.endpoint:
            raise ParseError("Docling endpoint not configured.")

        headers = {}
        if hasattr(settings, "DOCLING_API_KEY") and settings.DOCLING_API_KEY:
            headers["X-Api-Key"] = settings.DOCLING_API_KEY

        # Parameters for Docling-serve
        data = [
            ("to_formats", "md"),
            ("to_formats", "json"),
            ("do_ocr", "true"),
            ("force_ocr", "true" if self.settings.force_ocr else "false"),
        ]

        if self.settings.language:
            lang_map = {
                "eng": "en",
                "deu": "de",
                "fra": "fr",
                "ita": "it",
                "spa": "es",
                "por": "pt",
                "nld": "nl",
                "rus": "ru",
                "jpn": "ja",
                "kor": "ko",
                "chi_sim": "ch_sim",
                "chi_tra": "ch_tra",
            }
            langs = [lang.strip() for lang in self.settings.language.split("+")]
            for lang in langs:
                mapped = lang_map.get(lang.lower(), lang.lower())
                data.append(("ocr_lang", str(mapped)))

        try:
            with file_path.open("rb") as f:
                files = {"files": (file_path.name, f, "application/octet-stream")}
                response = requests.post(
                    f"{self.settings.endpoint}/v1alpha/convert/file/async",
                    data=data,
                    files=files,
                    headers=headers,
                    timeout=30,
                )
            response.raise_for_status()
            task_id = response.json()["task_id"]
        except Exception as e:
            self.log.error(f"Failed to start Docling conversion: {e}")
            raise ParseError(f"Docling server communication failed: {e}")

        start_time = time.time()
        while True:
            if time.time() - start_time > self.settings.timeout:
                raise ParseError(
                    f"Docling conversion timed out after {self.settings.timeout}s",
                )

            time.sleep(2)
            try:
                response = requests.get(
                    f"{self.settings.endpoint}/v1alpha/status/poll/{task_id}",
                    headers=headers,
                    timeout=10,
                )
                response.raise_for_status()
                status_data = response.json()
                task_status = status_data.get("task_status", "").lower()

                if task_status in ["success", "finished", "completed"]:
                    result_response = requests.get(
                        f"{self.settings.endpoint}/v1alpha/result/{task_id}",
                        headers=headers,
                        timeout=30,
                    )
                    result_response.raise_for_status()
                    return DoclingServerResult.model_validate(result_response.json())

                if task_status in ["failure", "failed"]:
                    raise ParseError(f"Docling task failed: {status_data}")
            except Exception as e:
                if isinstance(e, ParseError):
                    raise
                self.log.warning(f"Docling polling error: {e}")

    def _convert_local(self, file_path: Path) -> DoclingServerResult:
        """
        Convert file using local Docling library
        """
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            raise ParseError(
                "Docling library not found. Install 'docling' or configure DOCLING_ENDPOINT.",
            )

        try:
            from docling.document_converter import DocumentConverter

            from paperless_docling.models import DoclingDocument

            converter = DocumentConverter()
            result = converter.convert(file_path)

            # Use model_validate to ensure the dict matches our schema
            json_content = DoclingDocument.model_validate(
                result.document.export_to_dict(),
            )

            return DoclingServerResult(
                document=ServerDocumentResponse(
                    filename=file_path.name,
                    md_content=result.document.export_to_markdown(),
                    json_content=json_content,
                ),
                status="success",
            )

        except Exception as e:
            raise ParseError(f"Local Docling conversion failed: {e}")

    def parse(self, document_path: Path, mime_type, file_name=None) -> None:
        """
        Parse the document using Docling
        """
        self.log.info(f"Docling parser started for {file_name}")

        processed_path = document_path
        if self.is_image(mime_type):
            processed_path = self.preprocess_image(document_path)

        if self.settings.endpoint:
            response = self._convert_server(processed_path)
        else:
            response = self._convert_local(processed_path)

        # Save artifacts for developers
        self._save_debug_artifacts(response)

        # Extract rich metadata for Phase 2 mapping
        self.metadata = self._extract_metadata(response)

        # Cache metadata for decoupled application (signals.py)
        if self.metadata:
            cache.set(
                f"docling_meta_{self.logging_group}",
                self.metadata,
                timeout=600,  # 10 minutes should be enough for consumption to finish
            )

        # Extract text content
        doc_data = response.document
        raw_md = doc_data.md_content or ""

        self.text = re.sub(
            r"!\[.*?\]\(data:image\/.*?;base64,.*?\)",
            "[Image]",
            raw_md,
        )

        # Return original as archive
        self.archive_path = document_path

        self.log.info(f"Docling parsing complete for {file_name}")
