import base64
import re
from pathlib import Path

import img2pdf
import litellm
import pikepdf
from django.conf import settings
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas

from documents.gotenberg import generate_pdf_from_markdown
from documents.parsers import ImageDocumentParser
from documents.parsers import ParseError
from documents.parsers import make_thumbnail_from_pdf
from documents.utils import run_subprocess
from paperless.config import OllamaConfig


class OllamaDocumentParser(ImageDocumentParser):
    """
    This parser uses Ollama API with deepseek-ocr model to extract text from rasterized documents.
    """

    logging_name = "paperless.parsing.ollama"

    def __init__(self, logging_group, progress_callback=None):
        super().__init__(logging_group, progress_callback)
        self.page_results = []
        self.page_original_dimensions = []  # Store (width, height) for each page

    def get_settings(self) -> OllamaConfig:
        """
        This parser uses the Ollama configuration settings to parse documents
        """
        return OllamaConfig()

    def get_thumbnail(self, document_path: Path, mime_type, file_name=None) -> Path:
        if self.settings.ollama_ocr_debug_thumbnail and self.page_results:
            self.log.info("Generating debug thumbnail with bounding boxes...")
            try:
                # Use the original page image (before resizing for DeepSeek-OCR)
                # Look for the original converted page images
                images = sorted(list(Path(self.tempdir).glob("page-*.png")))
                if not images:
                    return super().get_thumbnail(document_path, mime_type, file_name)

                first_image = images[0]
                ocr_data = self._parse_ocr_coordinates(self.page_results[0])

                # Get original dimensions if available
                if self.page_original_dimensions:
                    orig_w, orig_h = self.page_original_dimensions[0]
                else:
                    # Fallback to image dimensions
                    with Image.open(first_image) as img:
                        orig_w, orig_h = img.size

                with Image.open(first_image) as img:
                    img = img.convert("RGB")
                    draw = ImageDraw.Draw(img)
                    w, h = img.size

                    for label, box in ocr_data:
                        # Box is [x1, y1, x2, y2] in 0-999 normalized coordinates
                        # Scale to original dimensions, then to current image size
                        x1, y1, x2, y2 = box
                        # First scale from 0-999 to original dimensions
                        x1_orig = (x1 * orig_w) / 1000
                        y1_orig = (y1 * orig_h) / 1000
                        x2_orig = (x2 * orig_w) / 1000
                        y2_orig = (y2 * orig_h) / 1000

                        # Then scale to current image dimensions (if different)
                        x1_img = (x1_orig * w) / orig_w
                        y1_img = (y1_orig * h) / orig_h
                        x2_img = (x2_orig * w) / orig_w
                        y2_img = (y2_orig * h) / orig_h

                        draw.rectangle(
                            [x1_img, y1_img, x2_img, y2_img],
                            outline="red",
                            width=3,
                        )
                        draw.text((x1_img, y1_img - 10), label, fill="red")

                    out_path = Path(self.tempdir) / "debug_thumbnail.webp"
                    img.save(out_path, format="WEBP")
                    return out_path
            except Exception as e:
                self.log.warning(f"Failed to generate debug thumbnail: {e}")

        return make_thumbnail_from_pdf(
            self.archive_path or document_path,
            self.tempdir,
            self.logging_group,
        )

    def _encode_image_to_base64(self, image_path: Path) -> str:
        """
        Encode image to base64 string.
        """
        with image_path.open("rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _call_ollama_api(self, image_base64: str, prompt: str) -> str:
        """
        Call Ollama API using litellm to extract text from image.
        """

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        ]

        response = litellm.completion(
            model=f"ollama/{self.settings.model}",
            messages=messages,
            stream=False,
            api_base=self.settings.endpoint,
            timeout=self.settings.timeout,
        )
        return response.choices[0].message.content

    def _convert_to_png(self, image_path: Path) -> Path:
        """
        Convert image to PNG format to ensure compatibility with Ollama/LiteLLM.
        """
        try:
            # If it's already a PNG, we might not need to convert, but
            # preprocessing might have saved it as something else if it complied with input.
            # We force PNG here.
            output_path = Path(self.tempdir) / f"{image_path.stem}_converted.png"

            with Image.open(image_path) as img:
                # specific handling for RGBA/P images if we were saving as JPEG, but PNG is fine.
                # Just save as PNG.
                img.save(output_path, format="PNG")

            return output_path
        except Exception as e:
            self.log.warning(f"Could not convert {image_path} to PNG: {e}")
            # If conversion fails, we fall back to the original and hope for the best
            # (though it will likely fail in the API if it was the cause)
            return image_path

    def _resize_for_deepseek_ocr(self, image_path: Path) -> tuple[Path, int, int]:
        """
        Resize image to 1024x1024 for DeepSeek-OCR model.
        Returns: (resized_image_path, original_width, original_height)
        """
        # Only resize if using deepseek-ocr model
        if "deepseek-ocr" not in self.settings.model.lower():
            with Image.open(image_path) as img:
                return image_path, img.width, img.height

        try:
            with Image.open(image_path) as img:
                original_width, original_height = img.size
                self.log.info(
                    f"Resizing image from {original_width}x{original_height} to 1024x1024 for DeepSeek-OCR",
                )

                # Resize maintaining aspect ratio, padding to 1024x1024
                img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

                # Create a new 1024x1024 white background image
                resized = Image.new("RGB", (1024, 1024), "white")

                # Paste the resized image centered
                offset = ((1024 - img.width) // 2, (1024 - img.height) // 2)
                resized.paste(img, offset)

                output_path = Path(self.tempdir) / f"{image_path.stem}_1024.png"
                resized.save(output_path, format="PNG")

                return output_path, original_width, original_height
        except Exception as e:
            self.log.warning(f"Could not resize {image_path} for DeepSeek-OCR: {e}")
            # Fallback to original
            with Image.open(image_path) as img:
                return image_path, img.width, img.height

    def _process_image(self, image_path: Path) -> tuple[str, int, int]:
        """
        Process a single image: preprocess, encode, call API.
        Returns: (ocr_result, original_width, original_height)
        """
        self.log.info(f"Processing image {image_path} with Ollama")
        processed_path = self.preprocess_image(image_path)

        # Ensure image is in a supported format (PNG) for the API
        processed_path = self._convert_to_png(processed_path)

        # Resize for DeepSeek-OCR if needed and get original dimensions
        resized_path, original_width, original_height = self._resize_for_deepseek_ocr(
            processed_path,
        )

        image_base64 = self._encode_image_to_base64(resized_path)
        prompt = (
            self.settings.prompt_template
            or "Extract text as Markdown with bounding boxes using <|ref|>text</|ref|><|det|>[[x1,y1,x2,y2]]</|det|> format."
        )
        self.log.info(f"Sending request to Ollama (model: {self.settings.model})...")
        result = self._call_ollama_api(image_base64, prompt)
        self.log.info("Ollama request finished.")
        return result, original_width, original_height

    def _parse_ocr_coordinates(self, raw_text: str) -> list[tuple[str, list[int]]]:
        """
        Parse DeepSeek-OCR tags to get labels and bounding boxes.
        Example: <|ref|>text<|/ref|><|det|>[[42, 433, 113, 522]]<|/det|>
        """
        results = []
        # Support both [[x,y,x,y]] and [x,y,x,y] just in case
        pattern = re.compile(
            r"<\|ref\|>(.*?)<\|/ref\|><\|det\|>\[?\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]\]?<\|/det\|>",
        )
        for match in pattern.finditer(raw_text):
            label = match.group(1)
            box = [int(match.group(i)) for i in range(2, 6)]
            results.append((label, box))
        return results

    def _filter_ocr_text(self, text: str) -> str:
        """
        Remove special tags from the extracted text while keeping the content.
        """
        # Remove <|det|>... tags entirely
        text = re.sub(r"<\|det\|>.*?<\|/det\|>", "", text, flags=re.DOTALL)
        # Remove <|ref|>...<|/ref|> tags AND their content
        text = re.sub(r"<\|ref\|>.*?<\|/ref\|>", "", text, flags=re.DOTALL)
        return text.strip()

    def _generate_overlay_pdf(
        self,
        image_path: Path,
        ocr_data: list[tuple[str, list[int]]],
        *,
        draw_boxes: bool = False,
        original_width: int | None = None,
        original_height: int | None = None,
    ) -> Path:
        """
        Generate a searchable PDF using reportlab overlay.
        If original_width/original_height are provided, coordinates will be scaled
        from normalized 0-999 to those dimensions instead of the image dimensions.
        """
        output_path = Path(self.tempdir) / f"{image_path.stem}_overlay.pdf"
        with Image.open(image_path) as img:
            w, h = img.size

        # Use original dimensions for coordinate scaling if provided
        coord_w = original_width if original_width else w
        coord_h = original_height if original_height else h

        c = canvas.Canvas(str(output_path), pagesize=(w, h))

        # Draw the base image
        c.drawImage(str(image_path), 0, 0, width=w, height=h)

        # Draw "invisible" text at coordinates
        # reportlab uses 0,0 as bottom-left
        for text, box in ocr_data:
            # Normalized coordinates 0-999
            x1, y1, _, y2 = box
            # Scale to original/target dimensions
            px1 = (x1 * coord_w) / 1000
            # Flip Y for reportlab (top-down 0-999 to bottom-up pixels)
            py1 = coord_h - (y2 * coord_h) / 1000
            py2 = coord_h - (y1 * coord_h) / 1000

            font_size = max(py2 - py1, 1)
            c.setFont("Helvetica", font_size)

            # Make text transparent
            c.setFillColor(Color(0, 0, 0, alpha=0))
            c.drawString(px1, py1, text)

            if draw_boxes:
                # Draw visible bounding box
                c.setStrokeColor(Color(1, 0, 0, alpha=1))  # Red
                c.setLineWidth(1)
                # width = scaled x2 - scaled x1
                # height = py2 - py1 (since py2 is top Y in cartesian)
                px2 = (box[2] * coord_w) / 1000
                rect_width = px2 - px1
                rect_height = py2 - py1
                c.rect(px1, py1, rect_width, rect_height, stroke=1, fill=0)

        c.showPage()
        c.save()
        return output_path

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

    def parse(self, document_path: Path, mime_type, file_name=None) -> None:
        """
        Parse the document using Ollama API.
        """
        self.log.info(f"Ollama parser started for {file_name} ({mime_type})")

        # Fallback for missing original file (common during reprocessing)
        if not document_path.exists():
            self.log.warning(f"Source file {document_path} missing.")
            # Check if we are a Document instance and have an archive?
            # Actually we just have document_path.
            # But the caller (tasks.py) might provide archive_path if we were smart?
            # No, tasks.py provides document.source_path.
            # Let's check for an archive.pdf in the same or related dir?
            # Better: check for archive path if we can find it.
            if (
                hasattr(self, "archive_path")
                and self.archive_path
                and self.archive_path.exists()
            ):
                self.log.info(f"Falling back to archive file: {self.archive_path}")
                document_path = self.archive_path
            else:
                # Try to guess archive path if we follow naming conventions
                potential_archive = Path(
                    str(document_path).replace("/originals/", "/archive/"),
                )
                if potential_archive.exists():
                    self.log.info(f"Guessed archive file fallback: {potential_archive}")
                    document_path = potential_archive

        if not document_path.exists():
            raise ParseError(f"Cannot find source file for {file_name}")

        try:
            self.page_results = []
            if mime_type == "application/pdf":
                # Convert PDF pages to images
                image_paths = self._convert_pdf_pages_to_images(document_path)
                texts = []
                overlay_pdfs = []
                total_pages = len(image_paths)

                for idx, image_path in enumerate(image_paths, start=1):
                    self.log.info(f"Processing page {idx}/{total_pages}")
                    raw_result, orig_w, orig_h = self._process_image(image_path)
                    self.page_results.append(raw_result)
                    self.page_original_dimensions.append((orig_w, orig_h))

                    text = self._filter_ocr_text(raw_result)
                    texts.append(text)

                    # Try to generate overlay PDF
                    ocr_data = self._parse_ocr_coordinates(raw_result)
                    if ocr_data:
                        overlay_pdfs.append(
                            self._generate_overlay_pdf(
                                image_path,
                                ocr_data,
                                draw_boxes=self.settings.ollama_ocr_debug_thumbnail,
                                original_width=orig_w,
                                original_height=orig_h,
                            ),
                        )

                    # Report progress after each page
                    self.progress(idx, total_pages)

                self.text = "\n\n".join(texts)

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
                raw_result, orig_w, orig_h = self._process_image(document_path)
                self.page_results.append(raw_result)
                self.page_original_dimensions.append((orig_w, orig_h))
                self.text = self._filter_ocr_text(raw_result)

                ocr_data = self._parse_ocr_coordinates(raw_result)
                if ocr_data:
                    self.archive_path = self._generate_overlay_pdf(
                        document_path,
                        ocr_data,
                        draw_boxes=self.settings.ollama_ocr_debug_thumbnail,
                        original_width=orig_w,
                        original_height=orig_h,
                    )

            elif mime_type in ["text/plain", "text/markdown"]:
                # For plain text/markdown, we just read it
                with document_path.open("r", encoding="utf-8", errors="replace") as f:
                    self.text = f.read()
            else:
                raise ParseError(f"Unsupported MIME type: {mime_type}")

            # If we don't have an archive yet, try Gotenberg
            if not self.archive_path:
                self.log.info("Generating PDF archive from markdown via Gotenberg...")
                generated_archive = generate_pdf_from_markdown(self.text, self.tempdir)
                if generated_archive:
                    self.archive_path = generated_archive
                else:
                    # Fallback methods
                    self.log.info(
                        "Gotenberg unavailable, using fallback archive method.",
                    )
                    if mime_type == "application/pdf":
                        # If Gotenberg fails, we DON'T want to set self.archive_path = document_path
                        # because tasks.py will shutil.move() it, effectively deleting the original
                        # from the originals folder.
                        # If we have no archive, we just leave self.archive_path as None.
                        # Paperless will then know there is no archive version.
                        self.log.info(
                            "No archive version generated (Gotenberg/Overlay failed).",
                        )
                        self.archive_path = None
                    elif self.is_image(mime_type):
                        archive_path = Path(self.tempdir) / "archive.pdf"
                        with document_path.open("rb") as f:
                            pdf_bytes = img2pdf.convert(f.read())
                        with archive_path.open("wb") as f:
                            f.write(pdf_bytes)
                        self.archive_path = archive_path
                    else:
                        # For text or others, create a simple PDF archive locally
                        self.log.info("Creating simple local PDF archive from text...")

                        # Create image of text (simple approach)
                        img = Image.new(
                            "RGB",
                            (2480, 3508),
                            color="white",
                        )  # A4 @ 300dpi roughly
                        draw = ImageDraw.Draw(img)
                        try:
                            font = ImageFont.truetype(
                                font=settings.THUMBNAIL_FONT_NAME,
                                size=40,
                            )
                        except Exception:
                            font = ImageFont.load_default()

                        # Draw text (first few lines)
                        draw.multiline_text(
                            (100, 100),
                            self.text[:5000],
                            font=font,
                            fill="black",
                            spacing=10,
                        )

                        archive_img = Path(self.tempdir) / "archive.png"
                        img.save(archive_img)

                        archive_path = Path(self.tempdir) / "archive.pdf"
                        with archive_img.open("rb") as f:
                            pdf_bytes = img2pdf.convert(f.read())
                        with archive_path.open("wb") as f:
                            f.write(pdf_bytes)
                        self.archive_path = archive_path

        except Exception as e:
            # Re-wrap known LLM exceptions
            if isinstance(e, litellm.Timeout):
                raise ParseError(
                    f"Ollama request timed out (limit: {self.settings.timeout}s). "
                    "Check if model is loaded.",
                ) from e
            if isinstance(e, (litellm.APIError, litellm.APIConnectionError)):
                raise ParseError(f"Ollama API error: {e}") from e

            # Fallback for other exceptions
            if not isinstance(e, ParseError):
                raise ParseError(f"Ollama parsing failed: {e}") from e
            raise
