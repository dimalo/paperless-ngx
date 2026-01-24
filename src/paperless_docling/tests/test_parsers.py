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

    def test_consumer_declaration(self):
        """Test that the parser is only registered when enabled."""
        from paperless_docling.signals import docling_consumer_declaration

        with self.settings(OCR_ENGINE="tesseract"):
            self.assertIsNone(docling_consumer_declaration(None))

        with self.settings(OCR_ENGINE="docling"):
            self.assertIsNotNone(docling_consumer_declaration(None))

        with self.settings(OCR_ENGINE="docling_server"):
            self.assertIsNotNone(docling_consumer_declaration(None))

    @mock.patch("httpx.Client")
    @mock.patch("paperless_docling.parsers.DoclingDocumentParser._generate_overlay_pdf")
    @mock.patch(
        "paperless_docling.parsers.DoclingDocumentParser._convert_pdf_pages_to_images",
    )
    def test_parse_success_pdf(
        self,
        mock_convert_images,
        mock_generate_overlay,
        mock_client,
    ):
        """Test successful parsing of a PDF document with overlay."""
        # Mock the httpx client
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None

        # Valid DoclingResponse JSON
        mock_response.json.return_value = {
            "document": {
                "name": "test_doc",
                "pages": {
                    "1": {"size": {"width": 100, "height": 100}, "page_no": 1},
                },
                "texts": [
                    {
                        "self_ref": "#/texts/1",
                        "label": "text",
                        "text": "Extracted text",
                        "prov": [
                            {
                                "page_no": 1,
                                "bbox": {
                                    "l": 10,
                                    "t": 10,
                                    "r": 50,
                                    "b": 50,
                                    "coord_origin": "BOTTOMLEFT",
                                },
                            },
                        ],
                    },
                ],
            },
            "md_content": "Extracted text from PDF",
        }
        mock_client.return_value.__enter__.return_value.post.return_value = (
            mock_response
        )

        # Mock image conversion
        mock_convert_images.return_value = [Path("page1.png")]
        # Mock overlay generation
        mock_generate_overlay.return_value = Path("overlay.pdf")

        # Mock pikepdf to avoid actual file operations on fake paths
        with mock.patch("pikepdf.Pdf"):
            with self.settings(OCR_ENGINE="docling_server"):
                parser = DoclingDocumentParser("test_group")
                test_file = self.SAMPLE_FILES / "test.pdf"
                test_file.write_bytes(b"fake pdf content")

                parser.parse(test_file, "application/pdf")

                self.assertEqual(parser.text, "Extracted text from PDF")
                self.assertIsNotNone(parser.archive_path)
                mock_client.return_value.__enter__.return_value.post.assert_called_once()
                mock_convert_images.assert_called_once()
                mock_generate_overlay.assert_called_once()

    @mock.patch("httpx.Client")
    def test_parse_validation_failure(self, mock_client):
        """Test parsing failure when response doesn't match model."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        # Missing required 'document' field in root or structure mismatch
        mock_response.json.return_value = {"something": "else"}
        mock_client.return_value.__enter__.return_value.post.return_value = (
            mock_response
        )

        parser = DoclingDocumentParser("test_group")
        test_file = self.SAMPLE_FILES / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        with self.settings(OCR_ENGINE="docling_server"):
            with self.assertRaises(ParseError) as context:
                parser.parse(test_file, "application/pdf")

        self.assertIn("Invalid response structure", str(context.exception))
