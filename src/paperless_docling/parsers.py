import json
import re
import time
from pathlib import Path
from typing import Any

import img2pdf
import pikepdf
import requests
from django.conf import settings
from PIL import Image
from pydantic import ValidationError
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas

from documents.parsers import ImageDocumentParser
from documents.parsers import ParseError
from documents.parsers import make_thumbnail_from_pdf
from documents.utils import run_subprocess
from paperless.config import DoclingConfig
from paperless_docling.models import DoclingServerResult
from paperless_docling.models import ServerDocumentResponse


class DoclingDocumentParser(ImageDocumentParser):
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

    def _convert_server(self, file_path: Path) -> DoclingServerResult:
        """
        Convert file using Docling-serve using the async task pipeline.
        We use requests here as it is more robust for multipart encoding in this environment.
        """
        headers = {}
        if hasattr(settings, "DOCLING_API_KEY") and settings.DOCLING_API_KEY:
            headers["X-Api-Key"] = settings.DOCLING_API_KEY

        data = [
            ("to_formats", "md"),
            ("to_formats", "json"),
            ("to_formats", "text"),
            ("do_ocr", "true"),
            ("force_ocr", "true" if self.settings.force_ocr else "false"),
            ("include_images", "false"),
            ("image_export_mode", "placeholder"),
        ]

        if self.settings.language:
            # Map 3-letter codes (Paperless/Tesseract) to 2-letter codes (EasyOCR/Docling Server)
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
            # Handle strings like 'deu + eng' by stripping whitespace
            langs = [lang.strip() for lang in self.settings.language.split("+")]
            for lang in langs:
                mapped = lang_map.get(lang.lower(), lang.lower())
                data.append(("ocr_lang", mapped))

        # 1. Start conversion
        with file_path.open("rb") as f:
            files = {"files": (file_path.name, f, "application/octet-stream")}
            response = requests.post(
                f"{self.settings.endpoint}/v1/convert/file/async",
                data=data,
                files=files,
                headers=headers,
                timeout=self.settings.timeout,
            )

        if response.status_code != 200:
            self.log.error(
                f"Docling start error ({response.status_code}): {response.text}",
            )
        response.raise_for_status()
        task_id = response.json()["task_id"]

        # 2. Poll for completion
        while True:
            time.sleep(1)
            response = requests.get(
                f"{self.settings.endpoint}/v1/status/poll/{task_id}",
                headers=headers,
                timeout=self.settings.timeout,
            )
            response.raise_for_status()
            status_data = response.json()
            task_status = status_data.get("task_status", "").lower()

            self.log.debug(f"Docling task {task_id} status: {task_status}")

            if task_status in ["success", "finished", "completed"]:
                result_response = requests.get(
                    f"{self.settings.endpoint}/v1/result/{task_id}",
                    headers=headers,
                    timeout=self.settings.timeout,
                )
                result_response.raise_for_status()
                result = result_response.json()
                break
            elif task_status in ["failure", "failed", "partial_success"]:
                # Try to get the result anyway, it might contain the error message
                try:
                    res = requests.get(
                        f"{self.settings.endpoint}/v1/result/{task_id}",
                        headers=headers,
                        timeout=5,
                    )
                    error_detail = res.text if res.status_code != 200 else res.json()
                except Exception:
                    error_detail = status_data

                self.log.error(f"Docling task failed: {error_detail}")
                raise ParseError(
                    f"Docling conversion failed ({task_status}): {error_detail}",
                )

            # If status is something else (pending, running, etc.), we continue polling.

        try:
            # Validate response structure
            return DoclingServerResult.model_validate(result)
        except ValidationError as e:
            self.log.error(f"Docling response validation failed: {e}")
            self.log.debug(f"Raw response: {json.dumps(result, default=str)}")
            raise ParseError(
                "Invalid response structure from Docling server",
            ) from e

    def _convert_local(self, file_path: Path) -> DoclingServerResult:
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
            # Export to dict matching the JSON structure
            document_dict = result.document.export_to_dict()
            markdown = result.document.export_to_markdown()

            return DoclingServerResult(
                document=ServerDocumentResponse(
                    filename=file_path.name,
                    md_content=markdown,
                    json_content=document_dict,
                ),
                status="success",
            )
        except Exception as e:
            raise ParseError(f"Local Docling conversion failed: {e}") from e

    def _convert_pdf_pages_to_images(self, pdf_path: Path) -> list[Path]:
        """
        Convert PDF pages to individual images using pdftoppm.
        """

        image_paths = []
        output_pattern = str(Path(self.tempdir) / "page")
        run_subprocess(
            [
                "pdftoppm",
                "-png",
                "-r",
                "300",  # DPI
                pdf_path,
                output_pattern,
            ],
            logger=self.log,
        )

        # Collect the generated image files
        for png_file in Path(self.tempdir).glob("page-*.png"):
            image_paths.append(png_file)

        return sorted(image_paths)

    def _generate_overlay_pdf(
        self,
        image_path: Path,
        raw_page_data: Any,
        texts_on_page: Any,
    ) -> Path:
        """
        Generate a searchable PDF using reportlab overlay.
        """
        output_path = Path(self.tempdir) / f"{image_path.stem}_overlay.pdf"
        with Image.open(image_path) as img:
            w, h = img.size

        # Support both Pydantic objects and raw dicts
        def val(obj, key, default=None):
            if obj is None:
                return default
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        page_size = val(raw_page_data, "size")
        doc_w = val(page_size, "width", 0)
        doc_h = val(page_size, "height", 0)
        page_no = val(raw_page_data, "page_no")

        c = canvas.Canvas(str(output_path), pagesize=(w, h))

        # Draw the base image
        c.drawImage(str(image_path), 0, 0, width=w, height=h)

        # Draw "invisible" text at coordinates
        for item in texts_on_page:
            text = val(item, "text")
            if not text:
                continue

            # Find provenance for this page
            prov_list = val(item, "prov", [])
            for prov in prov_list:
                if val(prov, "page_no") != page_no:
                    continue

                bbox = val(prov, "bbox")
                if not bbox:
                    continue

                # Box keys: left, top, right, bottom, coord_origin
                # Note: models.py uses alias 'l' for 'left', etc.
                # If it's a dict, we might see 'l'. If it's a Pydantic object, we see 'left'.
                left = (
                    val(bbox, "left")
                    if val(bbox, "left") is not None
                    else val(bbox, "l")
                )
                top = (
                    val(bbox, "top") if val(bbox, "top") is not None else val(bbox, "t")
                )
                bottom = (
                    val(bbox, "bottom")
                    if val(bbox, "bottom") is not None
                    else val(bbox, "b")
                )
                origin = val(bbox, "coord_origin", "BOTTOMLEFT")

                if left is None or top is None or bottom is None:
                    continue

                # Parse coordinates considering origin
                if origin == "TOPLEFT":
                    # Flip Y
                    bottom, top = (doc_h - top), (doc_h - bottom)

                # Now we have strict Bottom-Left origin coordinates relative to doc_w/doc_h
                # Scale to image dimensions w/h
                scale_x = w / doc_w if doc_w else 1
                scale_y = h / doc_h if doc_h else 1

                rect_left = left * scale_x
                rect_bottom = bottom * scale_y
                rect_top = top * scale_y

                # Calculate font size roughly
                rect_height = abs(rect_top - rect_bottom)
                font_size = max(rect_height, 1)

                c.setFont("Helvetica", font_size)

                # Make text transparent
                c.setFillColor(Color(0, 0, 0, alpha=0))
                # Draw text at bottom-left of rect
                c.drawString(rect_left, rect_bottom, text)

        c.showPage()
        c.save()
        return output_path

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
            from paperless.models import ApplicationConfiguration

            config = ApplicationConfiguration.objects.first()
            ocr_engine = (
                config.ocr_engine
                if config and config.ocr_engine
                else settings.OCR_ENGINE
            )

            if ocr_engine == "docling":
                self.log.info("Using Local Docling library")
                response = self._convert_server_result = self._convert_local(
                    processed_path,
                )
            else:
                self.log.info("Using Docling Server")
                response = self._convert_server_result = self._convert_server(
                    processed_path,
                )

            # Robust extraction logic to handle various response formats
            # and prevent 'NoneType' or 'AttributeError' crashes.
            doc_data = response.document

            # 1. Extract and Sanitize Text Content
            # We prefer Markdown for structure, but will fall back to plain text.
            raw_md = ""
            raw_text = ""
            if isinstance(doc_data, dict):
                raw_md = doc_data.get("md_content") or ""
                raw_text = doc_data.get("text_content") or ""
            elif hasattr(doc_data, "md_content"):
                raw_md = getattr(doc_data, "md_content", "") or ""
                raw_text = getattr(doc_data, "text_content", "") or ""

            if not raw_md and hasattr(response, "md_content"):
                raw_md = response.md_content or ""

            # Sanitize Markdown from any base64 images that might still be there
            self.text = re.sub(
                r"!\[.*?\]\(data:image\/.*?;base64,.*?\)",
                "[Image]",
                raw_md,
            )

            # If MD is still empty or looks like just placeholders, use plain text
            if (not self.text.strip() or self.text.strip() == "[Image]") and raw_text:
                self.text = raw_text

            if not self.text.strip():
                self.log.warning("No text content found in Docling response.")

            # 2. Extract JSON Document Data
            json_doc = None
            if isinstance(doc_data, dict):
                # If doc_data has json_content, use it, otherwise use doc_data itself
                json_doc = doc_data.get("json_content") or doc_data
            elif hasattr(doc_data, "json_content"):
                json_doc = doc_data.json_content or doc_data
            else:
                json_doc = doc_data

            # Generate Overlay PDF
            if mime_type == "application/pdf":
                if not json_doc:
                    self.log.error("No JSON content found in Docling response.")
                    return

                # If json_doc is still a dict at this point, try to coerce or access
                pages_info = (
                    getattr(json_doc, "pages", {})
                    if not isinstance(json_doc, dict)
                    else json_doc.get("pages", {})
                )
                texts = (
                    getattr(json_doc, "texts", [])
                    if not isinstance(json_doc, dict)
                    else json_doc.get("texts", [])
                )

                # Convert original PDF to images to use as background
                image_paths = self._convert_pdf_pages_to_images(document_path)
                overlay_pdfs = []

                # Iterate PDF pages
                for i, image_path in enumerate(image_paths, start=1):
                    # pages_info is a dict[str, PageItem] usually by page number (as str or int?)
                    # In models.py we defined it as Dict[str, PageItem]. Docling usually keys by "1" etc.
                    page_data = pages_info.get(str(i))
                    if not page_data:
                        # Try int key just in case model validation allowed it or coerced it differently
                        # types say Dict[str, PageItem] so accessing with int key on a dict might fail look up if key is str.
                        # But let's assume str key.
                        self.log.warning(f"No Docling data for page {i}")
                        continue

                    overlay_pdf = self._generate_overlay_pdf(
                        image_path,
                        page_data,
                        texts,
                    )
                    overlay_pdfs.append(overlay_pdf)

                if overlay_pdfs:
                    self.log.info(
                        f"Merging {len(overlay_pdfs)} overlay pages into archive...",
                    )
                    final_archive = Path(self.tempdir) / "archive.pdf"
                    with pikepdf.Pdf.new() as merged:
                        for pdf_page in overlay_pdfs:
                            with pikepdf.Pdf.open(pdf_page) as src:
                                merged.pages.extend(src.pages)
                        merged.save(final_archive)
                    self.archive_path = final_archive

            elif self.is_image(mime_type):
                # Single page
                if not json_doc:
                    self.log.error("No JSON content found in Docling response.")
                    return

                # If json_doc is still a dict at this point, try to coerce or access
                pages_info = (
                    getattr(json_doc, "pages", {})
                    if not isinstance(json_doc, dict)
                    else json_doc.get("pages", {})
                )
                texts = (
                    getattr(json_doc, "texts", [])
                    if not isinstance(json_doc, dict)
                    else json_doc.get("texts", [])
                )

                # Assume page 1
                page_data = pages_info.get("1")

                if page_data:
                    self.archive_path = self._generate_overlay_pdf(
                        processed_path,
                        page_data,
                        texts,
                    )

            # Fallback to Gotenberg if overlay failed or not applicable
            if not self.archive_path:
                from documents.gotenberg import generate_pdf_from_markdown

                generated_archive = None
                if self.text:
                    self.log.info(
                        "Generating archive using Gotenberg (Overlay skipped/failed)",
                    )
                    generated_archive = generate_pdf_from_markdown(
                        self.text,
                        self.tempdir,
                    )

                if generated_archive:
                    self.archive_path = generated_archive
                else:
                    if mime_type == "application/pdf":
                        self.log.info("No archive version generated.")
                        self.archive_path = None
                    elif self.is_image(mime_type):
                        # Standard image fallback (convert to simple PDF)
                        archive_path = Path(self.tempdir) / "archive.pdf"
                        with processed_path.open("rb") as f:
                            pdf_bytes = img2pdf.convert(f.read())
                        with archive_path.open("wb") as f:
                            f.write(pdf_bytes)
                        self.archive_path = archive_path

        except requests.exceptions.HTTPError as e:
            self.log.error(
                f"Docling server returned {e.response.status_code}: {e.response.text}",
            )
            raise ParseError(
                f"Docling server error ({e.response.status_code}): {e.response.text}",
            ) from e
        except requests.exceptions.Timeout as e:
            raise ParseError(
                f"Docling request timed out (limit: {self.settings.timeout}s).",
            ) from e
        except requests.exceptions.RequestException as e:
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
