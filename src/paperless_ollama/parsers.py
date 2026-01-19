import base64
import json
from pathlib import Path

import httpx

from documents.parsers import ParseError
from documents.parsers import make_thumbnail_from_pdf
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
        Call Ollama API to extract text from image.
        """
        payload = {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": f"{prompt}\n\n![image](data:image/png;base64,{image_base64})",
                },
            ],
            "stream": False,
        }

        with httpx.Client(timeout=self.settings.timeout) as client:
            response = client.post(
                f"{self.settings.endpoint}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
            return result["message"]["content"]

    def _process_image(self, image_path: Path) -> str:
        """
        Process a single image: preprocess, encode, call API.
        """
        processed_path = self.preprocess_image(image_path)
        image_base64 = self._encode_image_to_base64(processed_path)
        prompt = self.settings.prompt_template or "Extract text as Markdown."
        return self._call_ollama_api(image_base64, prompt)

    def _convert_pdf_pages_to_images(self, pdf_path: Path) -> list[Path]:
        """
        Convert PDF pages to individual images using pdftoppm.
        """
        from documents.utils import run_subprocess

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
        try:
            if mime_type == "application/pdf":
                # Convert PDF pages to images
                image_paths = self._convert_pdf_pages_to_images(document_path)
                texts = []
                for image_path in image_paths:
                    text = self._process_image(image_path)
                    texts.append(text)
                self.text = "\n\n".join(texts)
                # For PDFs, set archive to original
                self.archive_path = document_path
            elif self.is_image(mime_type):
                self.text = self._process_image(document_path)
                # For images, create PDF archive using img2pdf
                import img2pdf

                archive_path = Path(self.tempdir) / "archive.pdf"
                with document_path.open("rb") as f:
                    pdf_bytes = img2pdf.convert(f.read())
                with archive_path.open("wb") as f:
                    f.write(pdf_bytes)
                self.archive_path = archive_path
            else:
                raise ParseError(f"Unsupported MIME type: {mime_type}")

        except httpx.RequestError as e:
            raise ParseError(f"Ollama API request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON response from Ollama: {e}")
        except KeyError as e:
            raise ParseError(f"Unexpected response format from Ollama: {e}")
        except Exception as e:
            raise ParseError(f"Ollama parsing failed: {e}") from e
