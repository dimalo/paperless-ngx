import tempfile
import uuid
from pathlib import Path
from unittest import mock

from django.test import TestCase

from documents.parsers import ParseError
from documents.tests.utils import DirectoriesMixin
from paperless_ollama.parsers import OllamaDocumentParser


class TestOllamaParser(DirectoriesMixin, TestCase):
    SAMPLE_FILES = Path(__file__).resolve().parent / "samples"

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
            parser.parse(image_path, "image/png")

            self.assertEqual(parser.text, "Extracted text from image.")
            self.assertIsNotNone(parser.archive_path)
        finally:
            image_path.unlink(missing_ok=True)

    def test_parse_pdf_success(self):
        """
        Test successful parsing of a PDF.
        """
        parser = OllamaDocumentParser(uuid.uuid4())

        with (
            mock.patch("litellm.completion") as mock_completion,
            mock.patch.object(
                parser,
                "_convert_pdf_pages_to_images",
                return_value=[Path("dummy.png")],
            ) as mock_convert,
            mock.patch.object(
                parser,
                "_process_image",
                return_value="Page 1 text.",
            ) as mock_process,
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
                parser.parse(pdf_path, "application/pdf")

                self.assertEqual(parser.text, "Page 1 text.")
                self.assertEqual(parser.archive_path, pdf_path)
                mock_convert.assert_called_once_with(pdf_path)
                mock_process.assert_called_once_with(Path("dummy.png"))
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

            parser._call_ollama_api("dummy_base64", "test prompt")

            call_args = mock_completion.call_args
            self.assertIsNotNone(call_args)

            # Check messages structure
            messages = call_args[1]["messages"]
            content = messages[0]["content"]

            self.assertEqual(len(content), 2)
            self.assertEqual(content[0]["type"], "image_url")
            self.assertEqual(content[1]["type"], "text")
            self.assertEqual(content[1]["text"], "test prompt")
