from pathlib import Path
from unittest import mock

from django.test import TestCase

from documents.parsers import ParseError
from documents.tests.utils import DirectoriesMixin
from paperless_docling.parsers import DoclingDocumentParser
from paperless_docling.signals import docling_consumer_declaration


@mock.patch("time.sleep", return_value=None)
class TestDoclingParser(DirectoriesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.test_group = "test_group"

    def test_consumer_declaration_disabled(self, _):
        """Test that the parser is NOT registered when not available."""
        with mock.patch(
            "paperless_docling.signals.is_docling_available",
            return_value=False,
        ):
            self.assertIsNone(docling_consumer_declaration(None))

    def test_consumer_declaration_enabled(self, _):
        """Test that the parser IS registered when available."""
        with mock.patch(
            "paperless_docling.signals.is_docling_available",
            return_value=True,
        ):
            declaration = docling_consumer_declaration(None)
            self.assertIsNotNone(declaration)
            self.assertEqual(declaration["engine_id"], "docling")

    @mock.patch("requests.post")
    @mock.patch("requests.get")
    def test_parse_server_success(self, mock_get, mock_post, _):
        """Test successful server parsing with polling."""
        with mock.patch("paperless_docling.parsers.DoclingConfig") as mock_config:
            mock_config.return_value.endpoint = "http://docling-server"
            mock_config.return_value.timeout = 120
            mock_config.return_value.force_ocr = False
            mock_config.return_value.language = "eng"

            parser = DoclingDocumentParser(self.test_group)

            # Mock 1: Initial Post (returns task_id)
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"task_id": "task-123"}

            # Mock 2: Polling Status (returns completed)
            mock_status = mock.Mock()
            mock_status.status_code = 200
            mock_status.json.return_value = {"task_status": "completed"}

            # Mock 3: Result Content
            mock_result = mock.Mock()
            mock_result.status_code = 200
            mock_result.json.return_value = {
                "document": {
                    "md_content": "# Hello World\n![img](data:image/png;base64,123)",
                    "json_content": {
                        "pages": {
                            "1": {"size": {"width": 100, "height": 100}, "page_no": 1},
                        },
                    },
                },
                "status": "success",
            }

            mock_get.side_effect = [mock_status, mock_result]

            test_file = Path(self.dirs.scratch_dir) / "test.pdf"
            test_file.write_bytes(b"fake content")

            parser.parse(test_file, "application/pdf")

            # Check Markdown sanitization
            self.assertEqual(parser.text, "# Hello World\n[Image]")
            # Archive should be original
            self.assertEqual(parser.archive_path, test_file)

    @mock.patch("requests.get")
    @mock.patch("requests.post")
    def test_parse_server_error(self, mock_post, mock_get, _):
        """Test server parsing failure handling."""
        with mock.patch("paperless_docling.parsers.DoclingConfig") as mock_config:
            mock_config.return_value.endpoint = "http://docling-server"
            mock_config.return_value.timeout = 120

            parser = DoclingDocumentParser(self.test_group)

            # Simulate a 500 error that raises when raise_for_status is called
            import requests

            mock_post.return_value.status_code = 500
            mock_post.return_value.raise_for_status.side_effect = requests.HTTPError(
                "500 Server Error",
            )

            test_file = Path(self.dirs.scratch_dir) / "test.pdf"
            test_file.write_bytes(b"fake content")

            with self.assertRaises(ParseError) as cm:
                parser.parse(test_file, "application/pdf")
            self.assertIn("server communication failed", str(cm.exception).lower())

            # Ensure it didn't even try to poll
            mock_get.assert_not_called()

    @mock.patch("paperless_docling.parsers.DoclingDocumentParser._convert_local")
    def test_parse_local_dispatch(self, mock_local, _):
        """Test that it chooses local when no endpoint is set."""
        from paperless_docling.models import DoclingServerResult
        from paperless_docling.models import ServerDocumentResponse

        with mock.patch("paperless_docling.parsers.DoclingConfig") as mock_config:
            mock_config.return_value.endpoint = None

            parser = DoclingDocumentParser(self.test_group)

            mock_local.return_value = DoclingServerResult(
                document=ServerDocumentResponse(md_content="local text"),
                status="success",
            )

            test_file = Path(self.dirs.scratch_dir) / "test.pdf"
            test_file.write_bytes(b"fake content")

            parser.parse(test_file, "application/pdf")
            mock_local.assert_called_once()
            self.assertEqual(parser.text, "local text")

    def test_coordinate_conversion(self, _):
        """Test BoundingBox coordinate normalization."""
        from paperless_docling.models import BoundingBox

        # Top-Left to Bottom-Left conversion
        # Page: 100x200
        # Box: l=5, t=10, r=50, b=30 (TOPLEFT)
        # Expected in BOTTOMLEFT:
        # top = 200 - 10 = 190
        # bottom = 200 - 30 = 170
        bbox = BoundingBox(l=5, t=10, r=50, b=30, coord_origin="TOPLEFT")
        converted = bbox.to_normalized_origin_bottom_left(100, 200)

        self.assertEqual(converted.left, 5)
        self.assertEqual(converted.top, 190)
        self.assertEqual(converted.bottom, 170)
        self.assertEqual(converted.coord_origin, "BOTTOMLEFT")

    def test_metadata_coercion(self, _):
        """Test _coerce_value for different data types."""
        from documents.models import CustomField
        from paperless_docling.utils import _coerce_value

        self.assertEqual(_coerce_value("123", CustomField.FieldDataType.INT), 123)
        self.assertEqual(_coerce_value("12.34", CustomField.FieldDataType.FLOAT), 12.34)
        self.assertEqual(
            _coerce_value("2023-01-01", CustomField.FieldDataType.DATE).isoformat(),
            "2023-01-01",
        )
        self.assertEqual(_coerce_value("yes", CustomField.FieldDataType.BOOL), True)
        self.assertEqual(_coerce_value("no", CustomField.FieldDataType.BOOL), False)
        # Monetary normalization
        self.assertEqual(
            _coerce_value("$ 1,234.56", CustomField.FieldDataType.MONETARY),
            "1,234.56",
        )

    def test_apply_metadata(self, _):
        """Test full metadata application flow."""
        from documents.models import CustomField
        from documents.models import CustomFieldInstance
        from documents.models import Document
        from documents.models import Tag
        from paperless_docling.utils import apply_docling_metadata

        doc = Document.objects.create(title="Test", content="...")
        field = CustomField.objects.create(
            name="Invoice Number",
            data_type=CustomField.FieldDataType.INT,
        )

        metadata = {
            "docling_labels": {"TABLE"},
            "docling_key_value": {"inv. no": "999"},
        }

        apply_docling_metadata(doc, metadata)

        # Check tag auto-creation
        self.assertTrue(Tag.objects.filter(name="Docling: Table").exists())
        self.assertIn(Tag.objects.get(name="Docling: Table"), doc.tags.all())

        # Check custom field mapping with synonym
        instance = CustomFieldInstance.objects.get(document=doc, field=field)
        self.assertEqual(instance.value, 999)
