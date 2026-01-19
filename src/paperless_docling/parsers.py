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

    def parse(self, document_path: Path, mime_type, file_name=None) -> None:
        """
        Parse the document using Docling-serve
        """
        try:
            processed_path = document_path
            if self.is_image(mime_type):
                processed_path = self.preprocess_image(document_path)

            # For large files, use async endpoint
            if processed_path.stat().st_size > 10 * 1024 * 1024:  # 10MB
                result = asyncio.run(self._convert_file_async(processed_path))
            else:
                result = self._convert_file_sync(processed_path)

            # Extract text content
            if "document" in result and "text_content" in result["document"]:
                self.text = result["document"]["text_content"]
            else:
                raise ParseError("No text content found in Docling response")

            # Generate PDF archive if needed
            if mime_type == "application/pdf":
                self.archive_path = document_path
            else:
                # For images, we need to create a PDF archive
                # Docling should provide a PDF, but for now assume it's handled
                pass

        except httpx.RequestError as e:
            raise ParseError(f"Docling request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON response from Docling: {e}")
        except KeyError as e:
            raise ParseError(f"Unexpected response format from Docling: {e}")
