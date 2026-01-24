import base64
from pathlib import Path

import img2pdf
import litellm
from django.conf import settings
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from documents.gotenberg import generate_pdf_from_markdown
from documents.parsers import ParseError
from documents.parsers import make_thumbnail_from_pdf
from documents.utils import run_subprocess
from paperless.config import OllamaConfig
from paperless_tesseract.parsers import RasterisedDocumentParser


class OllamaDocumentParser(RasterisedDocumentParser):
    """
    This parser uses Ollama API with deepseek-ocr model to extract text from rasterized documents.
    """

    logging_name = "paperless.parsing.ollama"

    def get_settings(self) -> OllamaConfig:
        """
        This parser uses the Ollama configuration settings to parse documents
        """
        return OllamaConfig()

    def get_thumbnail(self, document_path: Path, mime_type, file_name=None) -> Path:
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
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                    },
                ],
            },
        ]

        response = litellm.completion(
            model=f"ollama/{self.settings.model}",
            messages=messages,
            api_base=self.settings.endpoint,
            timeout=self.settings.timeout,
        )
        return response.choices[0].message.content

    def _process_image(self, image_path: Path) -> str:
        """
        Process a single image: preprocess, encode, call API.
        """
        self.log.info(f"Processing image {image_path} with Ollama")
        processed_path = self.preprocess_image(image_path)
        image_base64 = self._encode_image_to_base64(processed_path)
        prompt = self.settings.prompt_template or "Extract text as Markdown."
        self.log.info(f"Sending request to Ollama (model: {self.settings.model})...")
        result = self._call_ollama_api(image_base64, prompt)
        self.log.info("Ollama request finished.")
        return result

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
        try:
            if mime_type == "application/pdf":
                # Convert PDF pages to images
                image_paths = self._convert_pdf_pages_to_images(document_path)
                texts = []
                for image_path in image_paths:
                    text = self._process_image(image_path)
                    texts.append(text)
                self.text = "\n\n".join(texts)
            elif self.is_image(mime_type):
                self.text = self._process_image(document_path)
            elif mime_type in ["text/plain", "text/markdown"]:
                # For plain text/markdown, we just read it
                with document_path.open("r", encoding="utf-8", errors="replace") as f:
                    self.text = f.read()
            else:
                raise ParseError(f"Unsupported MIME type: {mime_type}")

            # Generate archive PDF from markdown
            self.log.info("Generating PDF archive from markdown via Gotenberg...")
            generated_archive = generate_pdf_from_markdown(self.text, self.tempdir)
            self.log.info(f"Gotenberg result: {generated_archive}")

            if generated_archive:
                self.archive_path = generated_archive
            else:
                # Fallback if Gotenberg unavailable
                self.log.info("Gotenberg unavailable, using fallback archive method.")
                if mime_type == "application/pdf":
                    self.archive_path = document_path
                elif self.is_image(mime_type):
                    # For images, create PDF archive using img2pdf
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
