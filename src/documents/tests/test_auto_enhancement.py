from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings

from documents.models import AIReviewQueue
from documents.models import AISuggestionHistory
from documents.models import Correspondent
from documents.models import Document
from documents.models import DocumentType
from documents.models import StoragePath
from documents.models import Tag
from documents.tasks import auto_enhance_document
from documents.tests.factories import DocumentFactory


class AutoEnhancementTestCase(TestCase):
    """Test cases for automatic AI document enhancement."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.document = DocumentFactory.create(owner=self.user)

    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @override_settings(PAPERLESS_AI_AUTO_ASSIGN=True)
    def test_auto_enhancement_disabled(self, mock_rate_limit, mock_ai_classify):
        """Test that enhancement is skipped when disabled."""
        with override_settings(PAPERLESS_AI_AUTO_ASSIGN=False):
            auto_enhance_document(self.document.pk)

            mock_ai_classify.assert_not_called()
            mock_rate_limit.assert_not_called()

    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @override_settings(PAPERLESS_AI_AUTO_ASSIGN=True)
    def test_rate_limit_exceeded(self, mock_rate_limit, mock_ai_classify):
        """Test that enhancement is skipped when rate limit is exceeded."""
        mock_rate_limit.return_value = False

        auto_enhance_document(self.document.pk)

        mock_rate_limit.assert_called_once_with(self.document.owner)
        mock_ai_classify.assert_not_called()

    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @override_settings(PAPERLESS_AI_AUTO_ASSIGN=True)
    def test_ai_service_unavailable_graceful_degradation(
        self,
        mock_rate_limit,
        mock_ai_classify,
    ):
        """Test graceful degradation when AI service is unavailable."""
        mock_rate_limit.return_value = True
        mock_ai_classify.side_effect = Exception("AI service down")

        with override_settings(GRACEFUL_DEGRADATION=True):
            auto_enhance_document(self.document.pk)

        mock_ai_classify.assert_called_once()
        # Should not raise exception, should log warning instead

    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @override_settings(PAPERLESS_AI_AUTO_ASSIGN=True)
    def test_ai_service_unavailable_no_graceful_degradation(
        self,
        mock_rate_limit,
        mock_ai_classify,
    ):
        """Test that exception is raised when AI service fails and graceful degradation is disabled."""
        mock_rate_limit.return_value = True
        mock_ai_classify.side_effect = Exception("AI service down")

        with override_settings(GRACEFUL_DEGRADATION=False):
            with self.assertRaises(Exception):
                auto_enhance_document(self.document.pk)

    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @override_settings(
        PAPERLESS_AI_AUTO_ASSIGN=True,
        PAPERLESS_AI_CONFIDENCE_THRESHOLD=0.8,
        PAPERLESS_AI_AUTO_CREATE_THRESHOLD=0.9,
    )
    def test_needs_review_logic(self, mock_rate_limit, mock_ai_classify):
        """Test that documents needing review are queued correctly."""
        mock_rate_limit.return_value = True

        # Mock AI result with mixed confidence scores requiring review
        ai_result = {
            "title": {"value": "Test Title", "confidence": 0.6},  # Needs review
            "tags": [{"name": "test-tag", "confidence": 0.6}],  # Needs review
            "correspondents": [{"name": "Test Corp", "confidence": 0.9}],  # Auto-apply
            "document_types": [{"name": "Invoice", "confidence": 0.9}],  # Auto-apply
            "storage_paths": [{"name": "Invoices", "confidence": 0.9}],  # Auto-apply
        }
        mock_ai_classify.return_value = ai_result

        auto_enhance_document(self.document.pk)

        # Should create review queue item
        review_items = AIReviewQueue.objects.filter(document=self.document)
        self.assertEqual(review_items.count(), 1)

        item = review_items.first()
        self.assertEqual(item.status, AIReviewQueue.Status.PENDING)
        self.assertEqual(item.suggestions["title"]["value"], "Test Title")
        self.assertEqual(item.confidence_scores["title"], 0.6)

        # Should not create history record since nothing was auto-applied
        history_items = AISuggestionHistory.objects.filter(document=self.document)
        self.assertEqual(history_items.count(), 0)

    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @patch("documents.tasks.auto_match_or_create_tags")
    @patch("documents.tasks.auto_match_or_create_correspondents")
    @patch("documents.tasks.auto_match_or_create_document_types")
    @patch("documents.tasks.auto_match_or_create_storage_paths")
    @override_settings(
        PAPERLESS_AI_AUTO_ASSIGN=True,
        PAPERLESS_AI_CONFIDENCE_THRESHOLD=0.7,
        PAPERLESS_AI_AUTO_CREATE_THRESHOLD=0.8,
    )
    def test_auto_apply_high_confidence(
        self,
        mock_storage_paths,
        mock_doc_types,
        mock_correspondents,
        mock_tags,
        mock_rate_limit,
        mock_ai_classify,
    ):
        """Test that high-confidence suggestions are auto-applied."""
        mock_rate_limit.return_value = True

        # Mock AI result with all high confidence scores
        ai_result = {
            "title": {"value": "High Confidence Title", "confidence": 0.9},
            "tags": [{"name": "important", "confidence": 0.9}],
            "correspondents": [{"name": "Big Corp", "confidence": 0.9}],
            "document_types": [{"name": "Receipt", "confidence": 0.9}],
            "storage_paths": [{"name": "Receipts", "confidence": 0.9}],
        }
        mock_ai_classify.return_value = ai_result

        # Mock the auto-match functions
        tag = Tag.objects.create(name="important", owner=self.user)
        correspondent = Correspondent.objects.create(name="Big Corp", owner=self.user)
        doc_type = DocumentType.objects.create(name="Receipt", owner=self.user)
        storage_path = StoragePath.objects.create(name="Receipts", owner=self.user)

        mock_tags.return_value = [tag]
        mock_correspondents.return_value = [correspondent]
        mock_doc_types.return_value = [doc_type]
        mock_storage_paths.return_value = [storage_path]

        auto_enhance_document(self.document.pk)

        # Refresh document from database
        self.document.refresh_from_db()

        # Check that suggestions were applied
        self.assertEqual(self.document.title, "High Confidence Title")
        self.assertIn(tag, self.document.tags.all())
        self.assertEqual(self.document.correspondent, correspondent)
        self.assertEqual(self.document.document_type, doc_type)
        self.assertEqual(self.document.storage_path, storage_path)

        # Should create history record
        history_items = AISuggestionHistory.objects.filter(document=self.document)
        self.assertEqual(history_items.count(), 1)

        history = history_items.first()
        self.assertEqual(
            history.applied_suggestions["title"]["value"],
            "High Confidence Title",
        )
        self.assertEqual(history.confidence_scores["title"], 0.9)
        self.assertEqual(history.applied_by, self.user)

        # Should not create review queue item
        review_items = AIReviewQueue.objects.filter(document=self.document)
        self.assertEqual(review_items.count(), 0)

    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @override_settings(
        PAPERLESS_AI_AUTO_ASSIGN=True,
        PAPERLESS_AI_CONFIDENCE_THRESHOLD=0.9,
    )
    def test_low_confidence_ignored(self, mock_rate_limit, mock_ai_classify):
        """Test that low-confidence suggestions are ignored."""
        mock_rate_limit.return_value = True

        # Mock AI result with all low confidence scores
        ai_result = {
            "title": {"value": "Low Confidence Title", "confidence": 0.3},
            "tags": [{"name": "maybe", "confidence": 0.3}],
            "correspondents": [{"name": "Small Corp", "confidence": 0.3}],
            "document_types": [{"name": "Note", "confidence": 0.3}],
            "storage_paths": [{"name": "Notes", "confidence": 0.3}],
        }
        mock_ai_classify.return_value = ai_result

        original_title = self.document.title

        auto_enhance_document(self.document.pk)

        # Refresh document from database
        self.document.refresh_from_db()

        # Check that nothing was changed
        self.assertEqual(self.document.title, original_title)
        self.assertEqual(self.document.tags.count(), 0)
        self.assertIsNone(self.document.correspondent)
        self.assertIsNone(self.document.document_type)
        self.assertIsNone(self.document.storage_path)

        # Should not create history or review items
        self.assertEqual(
            AISuggestionHistory.objects.filter(document=self.document).count(),
            0,
        )
        self.assertEqual(
            AIReviewQueue.objects.filter(document=self.document).count(),
            0,
        )

    def test_confidence_threshold_edge_cases(self):
        """Test edge cases for confidence thresholds."""
        # Test that 0.5 exactly triggers review
        ai_result = {
            "title": {"value": "Edge Case", "confidence": 0.5},
            "tags": [],
            "correspondents": [],
            "document_types": [],
            "storage_paths": [],
        }

        from documents.tasks import needs_review

        self.assertTrue(needs_review(ai_result))

        # Test that 0.49 does not trigger review
        ai_result["title"]["confidence"] = 0.49
        self.assertFalse(needs_review(ai_result))

        # Test that 0.7 exactly does not trigger review (assuming 0.7 threshold)
        ai_result["title"]["confidence"] = 0.7
        self.assertFalse(needs_review(ai_result))

    def test_document_not_found(self):
        """Test handling of non-existent document."""
        # Should not raise exception, should log error
        auto_enhance_document(99999)

        # Document should still not exist
        with self.assertRaises(Document.DoesNotExist):
            Document.objects.get(pk=99999)
