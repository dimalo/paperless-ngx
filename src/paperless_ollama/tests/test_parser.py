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
    @mock.patch("httpx.Client")
    def test_parse_image_success(self, mock_client, mock_img2pdf):
        """
        Test successful parsing of an image.
        """
        parser = OllamaDocumentParser(uuid.uuid4())

        mock_response = mock.Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "message": {"content": "Extracted text from image."},
        }
        mock_client.return_value.__enter__.return_value = mock_client.return_value
        mock_client.return_value.post.return_value = mock_response

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
            mock.patch("httpx.Client") as mock_client,
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
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"message": {"content": "Page 1 text."}}
            mock_client.return_value.__enter__.return_value = mock_client.return_value
            mock_client.return_value.post.return_value = mock_response

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

        with mock.patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value = mock_client.return_value
            mock_client.return_value.post.side_effect = Exception("API error")

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image_path = Path(tmp.name)
                tmp.write(b"dummy image data")

            try:
                with self.assertRaises(ParseError):
                    parser.parse(image_path, "image/png")
            finally:
                image_path.unlink(missing_ok=True)

    def test_parse_unsupported_mime_type(self):
        """
        Test parsing with unsupported MIME type.
        """
        parser = OllamaDocumentParser(uuid.uuid4())

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            file_path = Path(tmp.name)
            tmp.write(b"dummy text")

        try:
            with self.assertRaises(ParseError):
                parser.parse(file_path, "text/plain")
        finally:
            file_path.unlink(missing_ok=True)
