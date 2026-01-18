import json
from pathlib import Path
from unittest import mock

from django.test import TestCase

from documents.parsers import ParseError
from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import FileSystemAssertsMixin
from paperless_docling.parsers import DoclingDocumentParser


class TestDoclingParser(DirectoriesMixin, FileSystemAssertsMixin, TestCase):
    SAMPLE_FILES = Path(__file__).resolve().parent / "samples"

    def setUp(self):
        super().setUp()
        # Create sample files directory if it doesn't exist
        self.SAMPLE_FILES.mkdir(exist_ok=True)

    @mock.patch("httpx.Client")
    def test_parse_success_pdf(self, mock_client):
        """Test successful parsing of a PDF document."""
        # Mock the httpx client
        mock_response = mock.Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "document": {
                "text_content": "Extracted text from PDF",
            },
        }
        mock_client.return_value.__enter__.return_value.post.return_value = (
            mock_response
        )

        parser = DoclingDocumentParser("test_group")
        test_file = self.SAMPLE_FILES / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        parser.parse(test_file, "application/pdf")

        self.assertEqual(parser.text, "Extracted text from PDF")
        mock_client.return_value.__enter__.return_value.post.assert_called_once()

    @mock.patch("httpx.Client")
    def test_parse_success_image(self, mock_client):
        """Test successful parsing of an image document."""
        # Mock the httpx client
        mock_response = mock.Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "document": {
                "text_content": "Extracted text from image",
            },
        }
        mock_client.return_value.__enter__.return_value.post.return_value = (
            mock_response
        )

        parser = DoclingDocumentParser("test_group")
        test_file = self.SAMPLE_FILES / "test.png"
        test_file.write_bytes(b"fake image content")

        parser.parse(test_file, "image/png")

        self.assertEqual(parser.text, "Extracted text from image")
        mock_client.return_value.__enter__.return_value.post.assert_called_once()

    @mock.patch("httpx.Client")
    def test_parse_failure_no_text_content(self, mock_client):
        """Test parsing failure when no text content is returned."""
        mock_response = mock.Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"document": {}}
        mock_client.return_value.__enter__.return_value.post.return_value = (
            mock_response
        )

        parser = DoclingDocumentParser("test_group")
        test_file = self.SAMPLE_FILES / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        with self.assertRaises(ParseError) as context:
            parser.parse(test_file, "application/pdf")

        self.assertIn("No text content found", str(context.exception))

    @mock.patch("httpx.Client")
    def test_parse_http_error(self, mock_client):
        """Test parsing when HTTP request fails."""
        mock_client.return_value.__enter__.return_value.post.side_effect = Exception(
            "HTTP Error"
        )

        parser = DoclingDocumentParser("test_group")
        test_file = self.SAMPLE_FILES / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        with self.assertRaises(ParseError) as context:
            parser.parse(test_file, "application/pdf")

        self.assertIn("Docling request failed", str(context.exception))

    @mock.patch("httpx.Client")
    def test_parse_invalid_json(self, mock_client):
        """Test parsing when invalid JSON is returned."""
        mock_response = mock.Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_client.return_value.__enter__.return_value.post.return_value = (
            mock_response
        )

        parser = DoclingDocumentParser("test_group")
        test_file = self.SAMPLE_FILES / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        with self.assertRaises(ParseError) as context:
            parser.parse(test_file, "application/pdf")

        self.assertIn("Invalid JSON response", str(context.exception))

    @mock.patch("httpx.AsyncClient")
    def test_parse_large_file_async(self, mock_async_client):
        """Test parsing of large files using async endpoint."""
        # Create a large file (>10MB)
        large_content = b"x" * (11 * 1024 * 1024)
        test_file = self.SAMPLE_FILES / "large.pdf"
        test_file.write_bytes(large_content)

        # Mock async responses
        mock_async_response = mock.Mock()
        mock_async_response.raise_for_status.return_value = None

        # Mock async post for task creation
        mock_async_client.return_value.__aenter__.return_value.post.return_value = (
            mock_async_response
        )
        mock_async_response.json.return_value = {"task_id": "test_task"}

        # Mock status polling
        mock_status_response = mock.Mock()
        mock_status_response.raise_for_status.return_value = None
        mock_status_response.json.return_value = {"status": "success"}
        mock_async_client.return_value.__aenter__.return_value.get.side_effect = [
            mock_status_response,  # First call to status
            mock.Mock(
                json=lambda: {"document": {"text_content": "Large file text"}},
                raise_for_status=lambda: None,
            ),  # Result
        ]

        parser = DoclingDocumentParser("test_group")
        parser.parse(test_file, "application/pdf")

        self.assertEqual(parser.text, "Large file text")
