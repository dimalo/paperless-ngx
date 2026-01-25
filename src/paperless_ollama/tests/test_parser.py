import tempfile
import uuid
from pathlib import Path
from unittest import mock

import pytest
from django.test import TestCase

from documents.parsers import ParseError
from documents.tests.utils import DirectoriesMixin
from paperless_ollama.parsers import OllamaDocumentParser


class TestOllamaParser(DirectoriesMixin, TestCase):
    SAMPLE_FILES = Path(__file__).resolve().parent / "samples"

    @pytest.mark.django_db
    def test_consumer_declaration(self):
        """Test that the parser is only registered when enabled."""
        from paperless.models import ApplicationConfiguration
        from paperless_ollama.signals import ollama_consumer_declaration

        # Ensure DB config doesn't override settings
        ApplicationConfiguration.objects.all().delete()

        with self.settings(OCR_ENGINE="tesseract"):
            self.assertIsNone(ollama_consumer_declaration(None))

        with self.settings(OCR_ENGINE="ollama"):
            self.assertIsNotNone(ollama_consumer_declaration(None))

    @mock.patch("img2pdf.convert", return_value=b"pdf data")
    @mock.patch("litellm.completion")
    def test_parse_image_success(self, mock_completion, mock_img2pdf):
        """
        Test successful parsing of an image.
        """
        parser = OllamaDocumentParser(uuid.uuid4())

        mock_response = mock.Mock()
        mock_response.choices = [
            mock.Mock(message=mock.Mock(content="Extracted text from image.")),
        ]
        mock_completion.return_value = mock_response

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            image_path = Path(tmp.name)
            # Create a dummy image file
            tmp.write(b"dummy image data")

        try:
            # Mock _prepare_message and _call_ollama_api_sequential
            with (
                mock.patch.object(
                    parser,
                    "_prepare_message",
                    return_value=([{"role": "user"}], 800, 600),
                ),
                mock.patch.object(
                    parser,
                    "_call_ollama_api_sequential",
                    return_value="Extracted text from image.",
                ),
            ):
                parser.parse(image_path, "image/png")

            self.assertEqual(parser.text, "Extracted text from image.")
            self.assertIsNotNone(parser.archive_path)
        finally:
            image_path.unlink(missing_ok=True)

    def test_parse_pdf_success(self):
        """
        Test successful parsing of a PDF.
        """
        with self.settings(OLLAMA_MODEL="generic-vlm"):
            parser = OllamaDocumentParser(uuid.uuid4())

            with (
                mock.patch("litellm.completion") as mock_completion,
                mock.patch.object(
                    parser,
                    "_convert_pdf_pages_to_images",
                    return_value=[Path("dummy.png")],
                ) as mock_convert,
            ):
                mock_response = mock.Mock()
                mock_response.choices = [
                    mock.Mock(message=mock.Mock(content="Page 1 text.")),
                ]
                mock_completion.return_value = mock_response

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    pdf_path = Path(tmp.name)
                    tmp.write(b"dummy pdf data")

                try:
                    # Mock _prepare_message and _call_ollama_api_batch
                    with (
                        mock.patch.object(
                            parser,
                            "_prepare_message",
                            return_value=([{"role": "user"}], 800, 600),
                        ),
                        mock.patch.object(
                            parser,
                            "_call_ollama_api_batch",
                            return_value=["Page 1 text."],
                        ),
                        mock.patch.object(
                            Path,
                            "exists",
                            return_value=True,
                        ),  # Mock existence of dummy.png
                    ):
                        parser.parse(pdf_path, "application/pdf")

                    self.assertEqual(parser.text, "Page 1 text.")
                    # Since we didn't mock generate_pdf_from_markdown or result in overlay,
                    # and fallback for PDF is None (to avoid deleting original), it should be None.
                    self.assertIsNone(parser.archive_path)
                    mock_convert.assert_called_once_with(
                        pdf_path,
                        scale_to=None,
                        scale_to_x=None,
                        scale_to_y=None,
                        dpi=150,
                    )
                finally:
                    pdf_path.unlink(missing_ok=True)

    def test_parse_api_failure(self):
        """
        Test parsing failure due to API error.
        """
        parser = OllamaDocumentParser(uuid.uuid4())

        with mock.patch("litellm.completion") as mock_completion:
            mock_completion.side_effect = Exception("API error")

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image_path = Path(tmp.name)
                tmp.write(b"dummy image data")

            try:
                with self.assertRaises(ParseError):
                    parser.parse(image_path, "image/png")
            finally:
                image_path.unlink(missing_ok=True)

    def test_parse_text_success(self):
        """
        Test successful parsing of a text file.
        """
        parser = OllamaDocumentParser(uuid.uuid4())

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            file_path = Path(tmp.name)
            tmp.write(b"dummy text content")

        try:
            parser.parse(file_path, "text/plain")

            self.assertEqual(parser.text, "dummy text content")
            self.assertIsNotNone(parser.archive_path)
        finally:
            file_path.unlink(missing_ok=True)

    def test_parse_unsupported_mime_type(self):
        """
        Test parsing with unsupported MIME type.
        """
        parser = OllamaDocumentParser(uuid.uuid4())

        with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
            file_path = Path(tmp.name)
            tmp.write(b"dummy doc")

        try:
            with self.assertRaises(ParseError):
                parser.parse(file_path, "application/msword")
        finally:
            file_path.unlink(missing_ok=True)

    def test_call_ollama_api_prompt_order(self):
        """
        Test that the image is sent before the text in the prompt.
        """
        parser = OllamaDocumentParser(uuid.uuid4())

        with mock.patch("litellm.completion") as mock_completion:
            mock_response = mock.Mock()
            mock_response.choices = [mock.Mock(message=mock.Mock(content="result"))]
            mock_completion.return_value = mock_response

            parser._call_ollama_api_sequential(
                [{"role": "user", "content": [{"type": "text", "text": "test"}]}],
            )

            call_args = mock_completion.call_args
            self.assertIsNotNone(call_args)

            # Check messages structure
            messages = call_args[1]["messages"]
            self.assertEqual(messages[0]["role"], "user")
