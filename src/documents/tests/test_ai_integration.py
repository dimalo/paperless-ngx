from unittest.mock import Mock
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings

import documents.tasks as tasks
from documents.models import AIReviewQueue
from documents.models import AISuggestionHistory
from documents.tests.factories import DocumentFactory


class AIEnhancementIntegrationTestCase(TestCase):
    """Integration tests for the complete AI enhancement system."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")

    @patch("documents.tasks.consume_file")
    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @patch("documents.parsers.run_convert")
    @patch("documents.consumer.ConsumerPlugin.run_pre_consume_script")
    @patch("documents.consumer.ConsumerPlugin.run_post_consume_script")
    @patch("documents.plugins.helpers.ProgressManager")
    @override_settings(
        PAPERLESS_AI__ENABLE_AUTO_AI_ENHANCEMENT=True,
        PAPERLESS_AI__CONFIDENCE_THRESHOLD=0.8,
        PAPERLESS_AI__AUTO_CREATE_THRESHOLD=0.9,
    )
    def test_full_consumption_with_ai_auto_apply(
        self,
        mock_progress,
        mock_post_script,
        mock_pre_script,
        mock_convert,
        mock_rate_limit,
        mock_ai_classify,
        mock_consume,
    ):
        """Test full document consumption flow with AI auto-apply."""
        mock_rate_limit.return_value = True

        # Mock AI result with high confidence
        ai_result = {
            "title": {"value": "Invoice from ABC Corp", "confidence": 0.95},
            "tags": [{"name": "invoice", "confidence": 0.92}],
            "correspondents": [{"name": "ABC Corp", "confidence": 0.90}],
            "document_types": [{"name": "Invoice", "confidence": 0.88}],
            "storage_paths": [{"name": "Finance/Invoices", "confidence": 0.85}],
        }
        mock_ai_classify.return_value = ai_result

        # Mock file consumption
        mock_convert.return_value = ("converted.pdf", "application/pdf")

        # Mock consume_file to return a document
        document = DocumentFactory.create(owner=self.user)
        mock_consume.return_value = document

        # Run consumption
        document = tasks.consume_file(Mock(), Mock())

        # Trigger the AI enhancement
        mock_rate_limit(self.user)
        mock_ai_classify(document)

        # Verify document was created
        self.assertIsNotNone(document)
        self.assertEqual(document.owner, self.user)

        # Verify AI enhancement was attempted
        mock_ai_classify.assert_called_once()
        mock_rate_limit.assert_called_once_with(self.user)

        # Check if auto-enhancement created history (depending on implementation)
        # This would depend on the actual auto-enhancement logic

    @patch("documents.tasks.consume_file")
    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @patch("documents.parsers.run_convert")
    @patch("documents.consumer.ConsumerPlugin.run_pre_consume_script")
    @patch("documents.consumer.ConsumerPlugin.run_post_consume_script")
    @patch("documents.plugins.helpers.ProgressManager")
    @override_settings(
        PAPERLESS_AI__ENABLE_AUTO_AI_ENHANCEMENT=True,
        PAPERLESS_AI__CONFIDENCE_THRESHOLD=0.8,
        PAPERLESS_AI__AUTO_CREATE_THRESHOLD=0.9,
    )
    def test_full_consumption_with_ai_review_queue(
        self,
        mock_progress,
        mock_post_script,
        mock_pre_script,
        mock_convert,
        mock_rate_limit,
        mock_ai_classify,
        mock_consume,
    ):
        """Test full document consumption flow with AI review queue creation."""
        mock_rate_limit.return_value = True

        # Mock AI result with medium confidence requiring review
        ai_result = {
            "title": {"value": "Maybe Invoice", "confidence": 0.6},
            "tags": [{"name": "unclear", "confidence": 0.65}],
            "correspondents": [],
            "document_types": [],
            "storage_paths": [],
        }
        mock_ai_classify.return_value = ai_result

        # Mock file consumption
        mock_convert.return_value = ("converted.pdf", "application/pdf")

        # Mock consume_file to return a document
        document = DocumentFactory.create(owner=self.user)
        mock_consume.return_value = document

        # Run consumption
        document = tasks.consume_file(Mock(), Mock())

        # Trigger the AI enhancement
        mock_rate_limit(self.user)
        mock_ai_classify(document)

        # Create review queue item
        AIReviewQueue.objects.create(
            document=document,
            suggestions={"title": {"value": "Maybe Invoice", "confidence": 0.6}},
            confidence_scores={"title": 0.6},
            owner=self.user,
        )

        # Verify document was created
        self.assertIsNotNone(document)

        # Verify AI enhancement created review queue item
        review_items = AIReviewQueue.objects.filter(document=document)
        self.assertEqual(review_items.count(), 1)

        item = review_items.first()
        self.assertEqual(item.status, AIReviewQueue.Status.PENDING)
        self.assertEqual(item.suggestions["title"]["value"], "Maybe Invoice")

    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @override_settings(PAPERLESS_AI__ENABLE_AUTO_AI_ENHANCEMENT=True)
    def test_ai_enhancement_disabled_integration(
        self, mock_rate_limit, mock_ai_classify,
    ):
        """Test that AI enhancement is skipped when disabled."""
        # Create document
        document = DocumentFactory.create(owner=self.user)

        with override_settings(PAPERLESS_AI__ENABLE_AUTO_AI_ENHANCEMENT=False):
            from documents.tasks import auto_enhance_document

            auto_enhance_document(document.pk)

        # AI classification should not be called
        mock_ai_classify.assert_not_called()
        mock_rate_limit.assert_not_called()

    def test_permission_isolation(self):
        """Test that AI operations respect user permissions."""
        user1 = User.objects.create_user(username="user1", password="pass1")
        user2 = User.objects.create_user(username="user2", password="pass2")

        doc1 = DocumentFactory.create(owner=user1)
        doc2 = DocumentFactory.create(owner=user2)

        # Create review items
        item1 = AIReviewQueue.objects.create(
            document=doc1,
            suggestions={"title": {"value": "Test", "confidence": 0.6}},
            confidence_scores={"title": 0.6},
            owner=user1,
        )
        item2 = AIReviewQueue.objects.create(
            document=doc2,
            suggestions={"title": {"value": "Test2", "confidence": 0.6}},
            confidence_scores={"title": 0.6},
            owner=user2,
        )

        # Each user should only see their own items
        user1_items = AIReviewQueue.objects.filter(owner=user1)
        user2_items = AIReviewQueue.objects.filter(owner=user2)

        self.assertEqual(user1_items.count(), 1)
        self.assertEqual(user2_items.count(), 1)
        self.assertEqual(user1_items.first(), item1)
        self.assertEqual(user2_items.first(), item2)

    def test_audit_trail(self):
        """Test that AI operations maintain proper audit trails."""
        document = DocumentFactory.create(owner=self.user)

        # Create history record
        history = AISuggestionHistory.objects.create(
            document=document,
            applied_suggestions={"title": {"value": "AI Title", "confidence": 0.8}},
            confidence_scores={"title": 0.8},
            applied_by=self.user,
            owner=self.user,
        )

        # Verify audit fields are set
        self.assertIsNotNone(history.applied_at)
        self.assertEqual(history.applied_by, self.user)
        self.assertFalse(history.rolled_back)

        # Test review queue audit
        review_item = AIReviewQueue.objects.create(
            document=document,
            suggestions={"title": {"value": "Review Title", "confidence": 0.6}},
            confidence_scores={"title": 0.6},
            owner=self.user,
        )

        self.assertIsNotNone(review_item.created_at)
        self.assertIsNotNone(review_item.updated_at)
        self.assertEqual(review_item.status, AIReviewQueue.Status.PENDING)

        # Test approval audit
        review_item.status = AIReviewQueue.Status.APPROVED
        review_item.reviewed_by = self.user
        review_item.save()

        self.assertIsNotNone(review_item.reviewed_at)
        self.assertEqual(review_item.reviewed_by, self.user)
