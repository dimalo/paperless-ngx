from unittest import mock

from django.core.cache import cache
from django.test import TransactionTestCase

from documents.models import Document
from documents.models import Tag
from documents.signals import document_consumption_finished


class TestDoclingSignals(TransactionTestCase):
    def test_apply_metadata_on_finish(self):
        """Test that the signal receiver correctly retrieves metadata from cache and applies it."""
        doc = Document.objects.create(title="Test", content="...")
        Tag.objects.create(name="Docling: Table")
        logging_group = "test_group_123"
        metadata = {"docling_labels": {"TABLE"}, "docling_key_value": {"key": "value"}}

        # Pre-populate cache
        cache.set(f"docling_meta_{logging_group}", metadata)

        # Send signal
        document_consumption_finished.send(
            sender=self.__class__,
            document=doc,
            logging_group=logging_group,
        )

        # Verify tag was applied (indirect proof that apply_docling_metadata was called)
        self.assertTrue(Tag.objects.filter(name="Docling: Table").exists())
        self.assertIn(Tag.objects.get(name="Docling: Table"), doc.tags.all())

        # Verify cache was cleared
        self.assertIsNone(cache.get(f"docling_meta_{logging_group}"))

    def test_no_metadata_in_cache(self):
        """Test that the receiver handles cases where no metadata is in cache."""
        doc = Document.objects.create(title="Test", content="...")
        logging_group = "test_group_empty"

        # Ensure cache is empty
        cache.delete(f"docling_meta_{logging_group}")

        with mock.patch("paperless_docling.utils.apply_docling_metadata") as mock_apply:
            document_consumption_finished.send(
                sender=self.__class__,
                document=doc,
                logging_group=logging_group,
            )
            mock_apply.assert_not_called()
