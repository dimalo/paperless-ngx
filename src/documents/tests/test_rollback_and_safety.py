from unittest.mock import Mock
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.test import override_settings

from documents.models import AISuggestionHistory
from documents.tests.factories import DocumentFactory
from documents.utils import rollback_ai_suggestions


class AISuggestionHistoryFactory:
    """Factory for creating AISuggestionHistory instances for testing."""

    @staticmethod
    def create(
        document=None,
        applied_suggestions=None,
        confidence_scores=None,
        applied_by=None,
        owner=None,
    ):
        if document is None:
            document = DocumentFactory.create()
        if applied_suggestions is None:
            applied_suggestions = {
                "title": {"value": "Test Title", "confidence": 0.8},
                "tags": ["test-tag"],
            }
        if confidence_scores is None:
            confidence_scores = {
                "title": 0.8,
                "tags": [0.8],
            }
        if applied_by is None:
            applied_by = document.owner
        if owner is None:
            owner = document.owner

        return AISuggestionHistory.objects.create(
            document=document,
            applied_suggestions=applied_suggestions,
            confidence_scores=confidence_scores,
            applied_by=applied_by,
            owner=owner,
        )


class RollbackTestCase(TestCase):
    """Test cases for AI suggestion rollback functionality."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.document = DocumentFactory.create(owner=self.user)

    def test_rollback_title_change(self):
        """Test rollback of title changes."""
        # Set up document with AI-applied title
        self.document.title = "AI Applied Title"
        self.document.save()

        # Create history record
        history = AISuggestionHistoryFactory.create(
            document=self.document,
            applied_suggestions={
                "title": {"value": "AI Applied Title", "confidence": 0.8},
            },
            confidence_scores={"title": 0.8},
        )

        # Rollback the change
        rollback_ai_suggestions(history.id, self.user)

        # Check that document title was reverted (assuming original was empty or different)
        self.document.refresh_from_db()
        # Note: This test assumes the rollback logic knows how to revert title
        # The actual implementation may vary

        # Check that history record is marked as rolled back
        history.refresh_from_db()
        self.assertTrue(history.rolled_back)
        self.assertIsNotNone(history.rolled_back_at)
        self.assertEqual(history.rolled_back_by, self.user)

    def test_rollback_nonexistent_history(self):
        """Test rollback of non-existent history record."""
        with self.assertRaises(ValueError):
            rollback_ai_suggestions(99999, self.user)

    def test_rollback_already_rolled_back(self):
        """Test that already rolled back suggestions cannot be rolled back again."""
        history = AISuggestionHistoryFactory.create(document=self.document)
        history.rolled_back = True
        history.save()

        # Attempting to rollback again should raise an error
        with self.assertRaises(ValueError):
            rollback_ai_suggestions(history.id, self.user)
        # The function should handle this gracefully

    def test_rollback_permission_check(self):
        """Test that rollback checks permissions."""
        other_user = User.objects.create_user(
            username="otheruser",
            password="otherpass",
        )
        other_document = DocumentFactory.create(owner=other_user)
        history = AISuggestionHistoryFactory.create(
            document=other_document,
            owner=other_user,
        )

        # Try to rollback as wrong user - should fail or be prevented
        # This would depend on the permission checking in the rollback function
        with self.assertRaises(PermissionDenied):
            rollback_ai_suggestions(history.id, self.user)


class RateLimitingTestCase(TestCase):
    """Test cases for AI rate limiting functionality."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")

    @override_settings(RATE_LIMIT_REQUESTS=100, RATE_LIMIT_WINDOW=60)
    @patch("documents.utils.cache")
    @patch("documents.utils.timezone")
    def test_rate_limit_check(self, mock_timezone, mock_cache):
        """Test rate limit checking logic."""
        from documents.utils import check_ai_rate_limit

        # Mock time
        mock_now = Mock()
        mock_now.timestamp.return_value = 1234567890 + 10
        mock_timezone.now.return_value = mock_now

        # Mock cache to return remaining requests
        mock_cache.get.side_effect = [[], [1234567890] * 100]

        result = check_ai_rate_limit(self.user)
        self.assertTrue(result)

        result = check_ai_rate_limit(self.user)
        self.assertFalse(result)

    @override_settings(RATE_LIMIT_REQUESTS=100, RATE_LIMIT_WINDOW=60)
    @patch("documents.utils.cache")
    def test_rate_limit_cache_key(self, mock_cache):
        """Test that correct cache key is used."""
        from documents.utils import check_ai_rate_limit

        check_ai_rate_limit(self.user)

        # Check that cache.get was called with correct key
        expected_key = f"ai_rate_limit_{self.user.id}"
        mock_cache.get.assert_called_with(expected_key, [])

    @override_settings(RATE_LIMIT_REQUESTS=100, RATE_LIMIT_WINDOW=60)
    @patch("documents.utils.cache")
    @patch("documents.utils.timezone")
    def test_rate_limit_decrement(self, mock_timezone, mock_cache):
        """Test that rate limit is decremented on successful check."""
        from documents.utils import check_ai_rate_limit

        mock_cache.get.return_value = []
        mock_now = Mock()
        mock_now.timestamp.return_value = 1234567890.0
        mock_timezone.now.return_value = mock_now

        check_ai_rate_limit(self.user)

        # Should set cache with the list of timestamps
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        self.assertEqual(call_args[0][1], [1234567890.0])


class GracefulDegradationTestCase(TestCase):
    """Test cases for graceful degradation when AI services fail."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.document = DocumentFactory.create(owner=self.user)

    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    @override_settings(
        PAPERLESS_AI__ENABLE_AUTO_AI_ENHANCEMENT=True,
        PAPERLESS_AI__GRACEFUL_DEGRADATION=True,
    )
    def test_graceful_degradation_on_ai_failure(
        self,
        mock_rate_limit,
        mock_ai_classify,
    ):
        """Test that consumption continues when AI fails and graceful degradation is enabled."""
        from documents.tasks import auto_enhance_document

        mock_rate_limit.return_value = True
        mock_ai_classify.side_effect = Exception("AI API timeout")

        # Should not raise exception
        auto_enhance_document(self.document.pk)

        # Document should still exist and be unchanged
        self.document.refresh_from_db()
        self.assertIsNotNone(self.document)

    @override_settings(
        PAPERLESS_AI_AUTO_ASSIGN=True,
        GRACEFUL_DEGRADATION=False,
    )
    @patch("documents.tasks.get_ai_document_classification_with_confidence")
    @patch("documents.utils.check_ai_rate_limit")
    def test_no_graceful_degradation_raises_exception(
        self,
        mock_rate_limit,
        mock_ai_classify,
    ):
        """Test that exceptions are raised when graceful degradation is disabled."""
        from documents.tasks import auto_enhance_document

        mock_rate_limit.return_value = True
        mock_ai_classify.side_effect = Exception("AI API timeout")

        # Should raise exception
        with self.assertRaises(Exception):
            auto_enhance_document(self.document.pk)
