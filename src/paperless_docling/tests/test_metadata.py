from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import TransactionTestCase

from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import Tag
from documents.signals import document_consumption_finished
from documents.tests.utils import DirectoriesMixin
from paperless_docling.parsers import DoclingDocumentParser


class TestDoclingMetadata(DirectoriesMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.test_group = "test-uuid-123"
        self.parser = DoclingDocumentParser(self.test_group)
        cache.clear()

    def test_parser_metadata_caching(self):
        """Test that the parser correctly caches metadata during parse."""
        mock_response = mock.MagicMock()
        mock_response.document.md_content = "some text"
        mock_response.document.json_content.key_value_items = [
            mock.MagicMock(key="Invoice Number", value="INV-001"),
        ]
        mock_response.document.json_content.tables = [mock.MagicMock()]
        mock_response.document.json_content.headings = []
        mock_response.document.json_content.texts = []

        test_file = Path(self.dirs.scratch_dir) / "test.pdf"
        test_file.write_bytes(b"pdf content")

        with mock.patch.object(
            self.parser,
            "_convert_local",
            return_value=mock_response,
        ):
            with mock.patch("paperless_docling.parsers.DoclingConfig") as mock_config:
                mock_config.return_value.endpoint = None
                self.parser.parse(test_file, "application/pdf")

        # Verify cache entry
        cached_meta = cache.get(f"docling_meta_{self.test_group}")
        self.assertIsNotNone(cached_meta)
        self.assertEqual(cached_meta["docling_key_value"]["Invoice Number"], "INV-001")
        self.assertIn("TABLE", cached_meta["docling_labels"])

    def test_signal_metadata_application(self):
        """Test that the signal receiver applies cached metadata to a document."""
        # 1. Setup environment
        tag = Tag.objects.create(name="Docling: Table")
        field = CustomField.objects.create(
            name="Invoice Number",
            data_type=CustomField.FieldDataType.STRING,
        )
        doc = Document.objects.create(title="Test Doc", content="test")

        metadata = {
            "docling_key_value": {"Invoice Number": "INV-2024"},
            "docling_labels": {"TABLE"},
        }

        # 2. Pre-cache metadata
        cache_key = f"docling_meta_{self.test_group}"
        cache.set(cache_key, metadata)

        # 3. Fire signal (simulating consumer finishing)
        document_consumption_finished.send(
            sender=None,
            document=doc,
            logging_group=self.test_group,
        )

        # 4. Verify results
        self.assertIn(tag, doc.tags.all())
        instance = CustomFieldInstance.objects.get(document=doc, field=field)
        self.assertEqual(instance.value, "INV-2024")

        # Verify cache cleanup
        self.assertIsNone(cache.get(cache_key))

    def test_synonym_mapping(self):
        """Test that common synonyms are mapped correctly."""
        field = CustomField.objects.create(
            name="Invoice Number",
            data_type=CustomField.FieldDataType.STRING,
        )
        doc = Document.objects.create(title="Test Doc", content="test")

        # docling finds "Inv. No", should map to "Invoice Number"
        metadata = {
            "docling_key_value": {"Inv. No": "INV-999"},
            "docling_labels": set(),
        }
        cache.set(f"docling_meta_{self.test_group}", metadata)

        document_consumption_finished.send(
            sender=None,
            document=doc,
            logging_group=self.test_group,
        )

        instance = CustomFieldInstance.objects.get(document=doc, field=field)
        self.assertEqual(instance.value, "INV-999")

    def test_no_existing_resources(self):
        """Test that it doesn't crash or create unwanted tags if they don't exist."""
        doc = Document.objects.create(title="Test Doc", content="test")
        metadata = {
            "docling_key_value": {"Unknown Field": "Value"},
            "docling_labels": {"HANDWRITTEN"},
        }
        cache.set(f"docling_meta_{self.test_group}", metadata)

        document_consumption_finished.send(
            sender=None,
            document=doc,
            logging_group=self.test_group,
        )

        # Should have no tags and no custom fields
        self.assertEqual(doc.tags.count(), 0)
        self.assertEqual(CustomFieldInstance.objects.filter(document=doc).count(), 0)
