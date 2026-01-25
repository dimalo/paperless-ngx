import base64
import re
import time
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

    BATCH_SIZE = 4
    MAX_RETRIES = 2

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
                        x1_orig, y1_orig, x2_orig, y2_orig = self._unscale_box(
                            box,
                            orig_w,
                            orig_h,
                        )

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
        Call Ollama API using litellm to extract text from image with retries.
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

        attempt = 0
        while True:
            try:
                response = litellm.completion(
                    model=f"ollama/{self.settings.model}",
                    messages=messages,
                    stream=False,
                    api_base=self.settings.endpoint or None,
                    timeout=self.settings.timeout or 120,
                )
                return response.choices[0].message.content
            except (litellm.Timeout, litellm.APIError, litellm.APIConnectionError) as e:
                attempt += 1
                if attempt > self.MAX_RETRIES:
                    self.log.error(
                        f"Ollama API call failed after {attempt} attempts: {e}",
                    )
                    raise
                self.log.warning(
                    f"Ollama API call failed (attempt {attempt}/{self.MAX_RETRIES + 1}), retrying: {e}",
                )
                # Small sleep before retry
                time.sleep(1)

    def _call_ollama_api_batch(self, messages_list: list[list[dict]]) -> list[str]:
        """
        Call Ollama API for multiple images in parallel using litellm.batch_completion.
        """
        attempt = 0
        while True:
            try:
                responses = litellm.batch_completion(
                    model=f"ollama/{self.settings.model}",
                    messages=messages_list,
                    api_base=self.settings.endpoint or None,
                    timeout=self.settings.timeout or 120,
                )
                # litellm.batch_completion can return a list where some items are exceptions
                # instead of Response objects. We need to check for this.
                results = []
                for idx, r in enumerate(responses):
                    if isinstance(r, Exception):
                        self.log.error(f"Batch item {idx} failed: {r}")
                        raise r
                    results.append(r.choices[0].message.content)
                return results
            except Exception as e:
                # litellm.batch_completion might throw if the whole batch fails
                # or if individual ones fail they might be in the list?
                # Usually it throws if it's a connection/timeout issue for the lot.
                attempt += 1
                if attempt > self.MAX_RETRIES:
                    self.log.error(
                        f"Ollama batch API call failed after {attempt} attempts: {e}",
                    )
                    raise
                self.log.warning(
                    f"Ollama batch API call failed (attempt {attempt}/{self.MAX_RETRIES + 1}), retrying: {e}",
                )
                time.sleep(1)

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
        Resize image to 1280x1280 for DeepSeek-OCR model.
        Returns: (resized_image_path, original_width, original_height)
        """
        # Only resize if using deepseek-ocr model
        if "deepseek-ocr" not in self.settings.model.lower():
            with Image.open(image_path) as img:
                return image_path, img.width, img.height

        target_size = 1280

        try:
            with Image.open(image_path) as img:
                original_width, original_height = img.size

                # If the image is already at the target size (e.g. from pdftoppm -scale-to),
                # we just need to ensure it's boxed into 1280x1280
                if original_width == target_size and original_height == target_size:
                    return image_path, original_width, original_height

                self.log.info(
                    f"Resizing image from {original_width}x{original_height} to {target_size}x{target_size} for DeepSeek-OCR",
                )

                # Resize maintaining aspect ratio, padding to target size
                img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)

                # Create a new white background image
                resized = Image.new("RGB", (target_size, target_size), "white")

                # Paste the resized image centered
                offset = (
                    (target_size - img.width) // 2,
                    (target_size - img.height) // 2,
                )
                resized.paste(img, offset)

                output_path = (
                    Path(self.tempdir) / f"{image_path.stem}_{target_size}.png"
                )
                resized.save(output_path, format="PNG")

                return output_path, original_width, original_height
        except Exception as e:
            self.log.warning(f"Could not resize {image_path} for DeepSeek-OCR: {e}")
            # Fallback to original
            with Image.open(image_path) as img:
                return image_path, img.width, img.height

    def _prepare_message(self, image_path: Path) -> tuple[list[dict], int, int]:
        """
        Prepare the message structure for a single image, including preprocessing.
        Returns: (messages, original_width, original_height)
        """
        self.log.info(f"Preparing image {image_path} for Ollama")
        processed_path = self.preprocess_image(image_path)
        processed_path = self._convert_to_png(processed_path)
        resized_path, original_width, original_height = self._resize_for_deepseek_ocr(
            processed_path,
        )

        image_base64 = self._encode_image_to_base64(resized_path)
        prompt = self.settings.prompt_template
        if not prompt:
            if "deepseek-ocr" in self.settings.model.lower():
                # Recommended DeepSeek-OCR prompt for document processing
                prompt = "<|grounding|>Convert the document to markdown."
            elif "qwen" in self.settings.model.lower():
                prompt = (
                    "OCR the image and extract all text content exactly as it appears. "
                    "Maintain the original layout and formatting where possible. "
                    "If the image contains multiple columns or tables, preserve the logical reading order."
                )
            else:
                prompt = "OCR this image. Extract all text content."

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
        return messages, original_width, original_height

    def _process_image(self, image_path: Path) -> tuple[str, int, int]:
        """
        Process a single image: preprocess, encode, call API.
        Returns: (ocr_result, original_width, original_height)
        """
        messages, original_width, original_height = self._prepare_message(image_path)

        self.log.info(f"Sending request to Ollama (model: {self.settings.model})...")
        result = self._call_ollama_api_sequential(messages)
        self.log.info("Ollama request finished.")
        return result, original_width, original_height

    def _call_ollama_api_sequential(self, messages: list[dict]) -> str:
        """
        Internal helper for sequential call with retries.
        """
        attempt = 0
        while True:
            try:
                response = litellm.completion(
                    model=f"ollama/{self.settings.model}",
                    messages=messages,
                    stream=False,
                    api_base=self.settings.endpoint or None,
                    timeout=self.settings.timeout or 120,
                )
                return response.choices[0].message.content
            except (litellm.Timeout, litellm.APIError, litellm.APIConnectionError) as e:
                attempt += 1
                if attempt > self.MAX_RETRIES:
                    raise
                self.log.warning(
                    f"Ollama API call failed (attempt {attempt}/{self.MAX_RETRIES + 1}), retrying: {e}",
                )
                time.sleep(1)

    def _unscale_box(self, box: list[int], orig_w: int, orig_h: int) -> list[float]:
        """
        Convert normalized 0-999 coordinates from DeepSeek-OCR back to original dimensions.
        Accounts for the 1280x1280 padding and centering.
        """
        x1, y1, x2, y2 = box

        if "deepseek-ocr" not in self.settings.model.lower():
            return [
                (x1 * orig_w) / 1000,
                (y1 * orig_h) / 1000,
                (x2 * orig_w) / 1000,
                (y2 * orig_h) / 1000,
            ]

        target = 1280
        # Calculate how PIL.Image.thumbnail and our padding logic works
        if orig_w <= target and orig_h <= target:
            new_w, new_h = orig_w, orig_h
        else:
            scale = min(target / orig_w, target / orig_h)
            new_w = round(orig_w * scale)
            new_h = round(orig_h * scale)

        offset_x = (target - new_w) // 2
        offset_y = (target - new_h) // 2

        def unscale_x(x_norm):
            x_pixel = (x_norm * target) / 1000
            return (x_pixel - offset_x) * orig_w / new_w

        def unscale_y(y_norm):
            y_pixel = (y_norm * target) / 1000
            return (y_pixel - offset_y) * orig_h / new_h

        return [
            unscale_x(x1),
            unscale_y(y1),
            unscale_x(x2),
            unscale_y(y2),
        ]

    def _parse_ocr_coordinates(self, raw_text: str) -> list[tuple[str, list[int]]]:
        """
        Parse DeepSeek-OCR tags to get labels and bounding boxes.
        Attempts to extract actual text content even if tags use generic labels.
        """
        results = []
        # Regex to capture content inside tags
        pattern = re.compile(
            r"<\|ref\|>(.*?)<\|/ref\|>\s*<\|det\|>\[?\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]\]?<\|/det\|>",
        )

        for match in pattern.finditer(raw_text):
            label = match.group(1).strip()
            box = [int(match.group(i)) for i in range(2, 6)]

            # Look ahead up to 200 characters for following text that isn't another tag
            end_pos = match.end()
            following_text = raw_text[end_pos : end_pos + 200]
            # Match first non-tag block of text
            text_match = re.search(r"^\s*([^<>\n\r]+)", following_text)

            # "Tag-like" means no spaces and relatively short
            is_tag_like = " " not in label and 1 < len(label) < 20

            if text_match:
                found_text = text_match.group(1).strip()
                # If we found following text, and the label is tag-like, prefer the following text
                if len(found_text) > 1 and is_tag_like:
                    label = found_text
            elif is_tag_like:
                # If no text follows but it's tag-like, escape it
                label = f"<!-- {label} -->"

            results.append((label, box))
        return results

    def _filter_ocr_text(self, text: str) -> str:
        """
        Remove special tags from the extracted text while keeping the content.
        Tries to handle cases where text is duplicated outside and inside tags.
        """
        # Remove <|det|> tags entirely
        text = re.sub(r"<\|det\|>.*?<\|/det\|>", "", text, flags=re.DOTALL)

        # For <|ref|> tags:
        # If the content is generic (text, subheading), we remove it assuming it was a label
        # Otherwise we keep the content but remove the tags
        def clean_ref(match):
            content = match.group(1).strip()
            if content.lower() in {
                "text",
                "subheading",
                "heading",
                "title",
                "paragraph",
            }:
                return ""
            return f" {content} "

        # Escape the pipes in the regex
        text = re.sub(r"<\|ref\|>(.*?)<\|/ref\|>", clean_ref, text, flags=re.DOTALL)

        # Collapse multiple spaces but preserve newlines
        text = re.sub(r"[ \t]+", " ", text)
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
            # Scale to original/target dimensions
            x1_orig, y1_orig, x2_orig, y2_orig = self._unscale_box(
                box,
                coord_w,
                coord_h,
            )

            # Flip Y for reportlab (top-down 0-999 to bottom-up pixels)
            px1 = x1_orig
            py1 = coord_h - y2_orig
            py2 = coord_h - y1_orig

            font_size = max(py2 - py1, 0.1)

            # Make text transparent
            c.setFillColor(Color(0, 0, 0, alpha=0))

            # Use textObject for horizontal scaling
            text_width = c.stringWidth(text, "Helvetica", font_size)
            target_width = max(x2_orig - x1_orig, 1)

            to = c.beginText(px1, py1)
            to.setFont("Helvetica", font_size)
            if text_width > target_width:
                scale = (target_width / text_width) * 100
                to.setHorizScale(scale)
            to.textOut(text)
            c.drawText(to)

            if draw_boxes:
                # Draw visible bounding box
                c.setStrokeColor(Color(1, 0, 0, alpha=1))  # Red
                c.setLineWidth(1)
                # width = scaled x2 - scaled x1
                # height = py2 - py1 (since py2 is top Y in cartesian)
                rect_width = x2_orig - x1_orig
                rect_height = py2 - py1
                c.rect(px1, py1, rect_width, rect_height, stroke=1, fill=0)

        c.showPage()
        c.save()
        return output_path

    def _convert_pdf_pages_to_images(
        self,
        pdf_path: Path,
        scale_to: int | None = None,
        scale_to_x: int | None = None,
        scale_to_y: int | None = None,
        dpi: int = 150,
    ) -> list[Path]:
        """
        Convert PDF pages to individual images using pdftoppm.
        Defaults to 150 DPI for better VLM performance/memory balance.
        """

        image_paths = []
        output_pattern = str(Path(self.tempdir) / "page")

        args = ["pdftoppm", "-png"]
        if scale_to_x and scale_to_y:
            args.extend(
                ["-scale-to-x", str(scale_to_x), "-scale-to-y", str(scale_to_y)],
            )
        elif scale_to:
            args.extend(["-scale-to", str(scale_to)])
        else:
            args.extend(["-r", str(dpi)])

        args.extend([str(pdf_path), str(output_pattern)])

        run_subprocess(args, logger=self.log)  # type: ignore

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
                # Determine scaling or DPI based on model
                scale_to = None
                scale_to_x = None
                scale_to_y = None
                dpi = 150  # Default to 150 DPI for VLMs

                model_lower = self.settings.model.lower()
                if "deepseek-ocr" in model_lower:
                    scale_to = 1280
                elif "qwen" in model_lower:
                    # Qwen models prefer dimensions to be multiples of 28
                    # We target roughly 120 DPI (~1M pixels)
                    try:
                        with pikepdf.Pdf.open(document_path) as pdf:
                            # Assume first page for calculating scaled dimensions
                            # (usually documents are uniform size, or we use first page as proxy)
                            page = pdf.pages[0]
                            # TrimBox/MediaBox are in points (1/72 inch)
                            box = page.MediaBox
                            w_pts = float(box[2]) - float(box[0])
                            h_pts = float(box[3]) - float(box[1])

                            dpi = 120
                            target_w = (w_pts / 72.0) * dpi
                            target_h = (h_pts / 72.0) * dpi

                            # Round to nearest multiple of 28
                            scale_to_x = int(round(target_w / 28.0) * 28)
                            scale_to_y = int(round(target_h / 28.0) * 28)
                    except Exception as e:
                        self.log.warning(
                            f"Could not calculate 28-pixel alignment for Qwen: {e}",
                        )
                        dpi = 120

                # Convert PDF pages to images
                image_paths = self._convert_pdf_pages_to_images(
                    document_path,
                    scale_to=scale_to,
                    scale_to_x=scale_to_x,
                    scale_to_y=scale_to_y,
                    dpi=dpi,
                )
                total_pages = len(image_paths)

                # Prepare all page messages
                all_messages = []
                all_orig_dims = []
                for idx, image_path in enumerate(image_paths, start=1):
                    self.log.info(f"Preparing page {idx}/{total_pages}")
                    messages, orig_w, orig_h = self._prepare_message(image_path)
                    all_messages.append(messages)
                    all_orig_dims.append((orig_w, orig_h))

                # Process in batches of 4
                raw_results = []
                for i in range(0, total_pages, self.BATCH_SIZE):
                    batch_messages = all_messages[i : i + self.BATCH_SIZE]
                    self.log.info(
                        f"Processing batch {i // self.BATCH_SIZE + 1} ({len(batch_messages)} pages)",
                    )
                    batch_results = self._call_ollama_api_batch(batch_messages)
                    raw_results.extend(batch_results)

                    # Update progress
                    current_progress = min(i + self.BATCH_SIZE, total_pages)
                    self.progress(current_progress, total_pages)

                # Process results
                texts = []
                overlay_pdfs = []
                for idx, (raw_result, (orig_w, orig_h)) in enumerate(
                    zip(raw_results, all_orig_dims),
                    start=1,
                ):
                    self.page_results.append(raw_result)
                    self.page_original_dimensions.append((orig_w, orig_h))

                    text = self._filter_ocr_text(raw_result)
                    texts.append(text)

                    # Try to generate overlay PDF
                    ocr_data = self._parse_ocr_coordinates(raw_result)
                    if ocr_data:
                        overlay_pdfs.append(
                            self._generate_overlay_pdf(
                                image_paths[idx - 1],
                                ocr_data,
                                draw_boxes=self.settings.ollama_ocr_debug_thumbnail,
                                original_width=orig_w,
                                original_height=orig_h,
                            ),
                        )

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
