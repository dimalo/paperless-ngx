import asyncio
import json
from pathlib import Path

import httpx
from django.conf import settings

from documents.parsers import ParseError
from documents.parsers import make_thumbnail_from_pdf
from paperless.config import DoclingConfig
from paperless_tesseract.parsers import RasterisedDocumentParser


class DoclingDocumentParser(RasterisedDocumentParser):
    """
    This parser uses Docling-serve to parse documents and extract text.
    """

    logging_name = "paperless.parsing.docling"

    def get_settings(self) -> DoclingConfig:
        """
        This parser uses the Docling configuration settings to parse documents
        """
        return DoclingConfig()

    def get_thumbnail(self, document_path: Path, mime_type, file_name=None) -> Path:
        return make_thumbnail_from_pdf(
            self.archive_path or document_path,
            self.tempdir,
            self.logging_group,
        )

    async def _convert_file_async(self, file_path: Path) -> dict:
        """
        Convert file using Docling-serve async endpoint
        """
        headers = {}
        if hasattr(settings, "DOCLING_API_KEY") and settings.DOCLING_API_KEY:
            headers["X-Api-Key"] = settings.DOCLING_API_KEY

        options = {
            "to_formats": ["text"],
            "do_ocr": True,
            "force_ocr": self.settings.force_ocr,
            "ocr_language": self.settings.language,
        }

        async with httpx.AsyncClient(timeout=self.settings.timeout) as client:
            # Start async conversion
            with file_path.open("rb") as f:
                files = {"files": (file_path.name, f, "application/octet-stream")}
                response = await client.post(
                    f"{self.settings.endpoint}/v1/convert/file/async",
                    files=files,
                    data={"options": json.dumps(options)},
                    headers=headers,
                )
            response.raise_for_status()
            task_id = response.json()["task_id"]

            # Poll for result
            while True:
                await asyncio.sleep(1)
                response = await client.get(
                    f"{self.settings.endpoint}/v1/status/poll/{task_id}",
                    headers=headers,
                )
                response.raise_for_status()
                status_data = response.json()

                if status_data["status"] == "success":
                    result_response = await client.get(
                        f"{self.settings.endpoint}/v1/result/{task_id}",
                        headers=headers,
                    )
                    result_response.raise_for_status()
                    return result_response.json()
                elif status_data["status"] in ["failure", "partial_success"]:
                    errors = status_data.get("errors", [])
                    raise ParseError(f"Docling conversion failed: {errors}")
                # Continue polling for other statuses

    def _convert_file_sync(self, file_path: Path) -> dict:
        """
        Convert file using Docling-serve sync endpoint
        """
        headers = {}
        if hasattr(settings, "DOCLING_API_KEY") and settings.DOCLING_API_KEY:
            headers["X-Api-Key"] = settings.DOCLING_API_KEY

        options = {
            "to_formats": ["text"],
            "do_ocr": True,
            "force_ocr": self.settings.force_ocr,
            "ocr_language": self.settings.language,
        }

        with httpx.Client(timeout=self.settings.timeout) as client:
            with file_path.open("rb") as f:
                files = {"files": (file_path.name, f, "application/octet-stream")}
                response = client.post(
                    f"{self.settings.endpoint}/v1/convert/file",
                    files=files,
                    data={"options": json.dumps(options)},
                    headers=headers,
                )
            response.raise_for_status()
            return response.json()

    def _convert_local(self, file_path: Path) -> str:
        """
        Convert file using local Docling library
        """
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as e:
            raise ParseError(
                "Docling python library not found. "
                "Set PAPERLESS_OCR_ENGINE='docling_server' or install 'docling'.",
            ) from e

        try:
            # TODO: Configure DocumentConverter with settings if needed (language etc)
            # Currently just using defaults as per requirement
            converter = DocumentConverter()
            result = converter.convert(file_path)
            return result.document.export_to_markdown()
        except Exception as e:
            raise ParseError(f"Local Docling conversion failed: {e}") from e

    def _convert_server(self, file_path: Path) -> str:
        """
        Convert file using Docling-serve (sync or async)
        """
        # For large files, use async endpoint
        if file_path.stat().st_size > 10 * 1024 * 1024:  # 10MB
            result = asyncio.run(self._convert_file_async(file_path))
        else:
            result = self._convert_file_sync(file_path)

        if "document" in result and "text_content" in result["document"]:
            return result["document"]["text_content"]
        else:
            raise ParseError("No text content found in Docling response")

    def parse(self, document_path: Path, mime_type, file_name=None) -> None:
        """
        Parse the document using Docling (Local or Server)
        """
        self.log.info(f"Docling parser started for {file_name} ({mime_type})")

        try:
            processed_path = document_path
            if self.is_image(mime_type):
                processed_path = self.preprocess_image(document_path)

            # Dispatch based on Engine setting
            # OCR_ENGINE is checked in settings.py to load this app, but we check here for mode
            if settings.OCR_ENGINE == "docling":
                self.log.info("Using Local Docling library")
                self.text = self._convert_local(processed_path)
            else:
                self.log.info("Using Docling Server")
                self.text = self._convert_server(processed_path)

            # Generate archive PDF from markdown
            from documents.gotenberg import generate_pdf_from_markdown

            generated_archive = None
            if self.text:
                generated_archive = generate_pdf_from_markdown(self.text, self.tempdir)

            if generated_archive:
                self.archive_path = generated_archive
            else:
                # Fallback if Gotenberg unavailable or no text
                if mime_type == "application/pdf":
                    # If Gotenberg fails, we DON'T want to set self.archive_path = document_path
                    # because tasks.py will shutil.move() it, effectively deleting the original
                    # from the originals folder.
                    self.log.info("No archive version generated (Gotenberg failed).")
                    self.archive_path = None

        except httpx.TimeoutException as e:
            raise ParseError(
                f"Docling request timed out (limit: {self.settings.timeout}s).",
            ) from e
        except httpx.RequestError as e:
            raise ParseError(f"Docling request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON response from Docling: {e}")
        except KeyError as e:
            raise ParseError(f"Unexpected response format from Docling: {e}")
        except ImportError as e:
            raise ParseError(f"Dependency missing: {e}") from e
        except Exception as e:
            if isinstance(e, ParseError):
                raise
            raise ParseError(f"Docling parsing failed: {e}") from e
