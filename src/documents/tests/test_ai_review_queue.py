from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from documents.models import AIReviewQueue
from documents.models import AISuggestionHistory
from documents.serialisers import AIReviewQueueSerializer
from documents.tests.factories import DocumentFactory


class AIReviewQueueFactory:
    """Factory for creating AIReviewQueue instances for testing."""

    @staticmethod
    def create(
        document=None,
        suggestions=None,
        confidence_scores=None,
        status=AIReviewQueue.Status.PENDING,
        owner=None,
    ):
        if document is None:
            document = DocumentFactory.create()
        if suggestions is None:
            suggestions = {
                "title": {"value": "Test Title", "confidence": 0.6},
                "tags": [{"name": "test-tag", "confidence": 0.6}],
            }
        if confidence_scores is None:
            confidence_scores = {
                "title": 0.6,
                "tags": [0.6],
            }
        if owner is None:
            owner = document.owner

        return AIReviewQueue.objects.create(
            document=document,
            suggestions=suggestions,
            confidence_scores=confidence_scores,
            status=status,
            owner=owner,
        )


class AIReviewQueueTestCase(TestCase):
    """Test cases for AIReviewQueue model."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.document = DocumentFactory.create(owner=self.user)

    def test_str_method(self):
        """Test string representation of AIReviewQueue."""
        review_item = AIReviewQueueFactory.create(document=self.document)
        expected = f"AI Review for {self.document.title} ({review_item.status})"
        self.assertEqual(str(review_item), expected)

    def test_unique_pending_constraint(self):
        """Test that only one pending review item can exist per document."""
        # Create first pending item
        AIReviewQueueFactory.create(document=self.document)

        # Try to create another pending item for same document - should fail
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            AIReviewQueueFactory.create(document=self.document)

    def test_ordering(self):
        """Test that items are ordered by created_at descending."""
        item1 = AIReviewQueueFactory.create(document=self.document)
        item2 = AIReviewQueueFactory.create(
            document=self.document,
            status=AIReviewQueue.Status.APPROVED,
        )

        # Force different creation times
        item1.created_at = timezone.now().replace(microsecond=0)
        item1.save()
        item2.created_at = item1.created_at + timezone.timedelta(seconds=1)
        item2.save()

        items = list(AIReviewQueue.objects.all())
        self.assertEqual(items[0], item2)  # Most recent first
        self.assertEqual(items[1], item1)

    def test_status_choices(self):
        """Test that status field accepts valid choices."""
        for status_choice in AIReviewQueue.Status:
            item = AIReviewQueueFactory.create(status=status_choice)
            self.assertEqual(item.status, status_choice)


class AIReviewQueueAPITestCase(APITestCase):
    """Test cases for AIReviewQueue API endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.other_user = User.objects.create_user(
            username="otheruser",
            password="otherpass",
        )
        # Add permissions for aireviewqueue
        perms = Permission.objects.filter(
            codename__in=[
                "view_aireviewqueue",
                "add_aireviewqueue",
                "change_aireviewqueue",
                "delete_aireviewqueue",
            ],
        )
        self.user.user_permissions.add(*perms)
        self.document = DocumentFactory.create(owner=self.user)
        self.other_document = DocumentFactory.create(owner=self.other_user)
        self.client.force_authenticate(user=self.user)

    def test_list_review_items(self):
        """Test listing AI review queue items."""
        item1 = AIReviewQueueFactory.create(document=self.document)
        _item2 = AIReviewQueueFactory.create(document=self.other_document)

        response = self.client.get("/api/ai_review/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should only see items owned by current user
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], item1.id)

    def test_retrieve_review_item(self):
        """Test retrieving a specific AI review queue item."""
        item = AIReviewQueueFactory.create(document=self.document)

        response = self.client.get(f"/api/ai_review/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], item.id)
        self.assertEqual(data["status"], item.status)
        self.assertEqual(data["document"], item.document.id)

    def test_cannot_access_other_users_item(self):
        """Test that users cannot access other users' review items."""
        item = AIReviewQueueFactory.create(document=self.other_document)

        response = self.client.get(f"/api/ai_review/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_bulk_approve(self):
        """Test bulk approve functionality."""
        document2 = DocumentFactory.create(owner=self.user)
        item1 = AIReviewQueueFactory.create(document=self.document)
        item2 = AIReviewQueueFactory.create(document=document2)

        response = self.client.post(
            "/api/ai_review/bulk-approve/",
            {"ids": [item1.id, item2.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Refresh from database
        item1.refresh_from_db()
        item2.refresh_from_db()

        self.assertEqual(item1.status, AIReviewQueue.Status.APPROVED)
        self.assertEqual(item2.status, AIReviewQueue.Status.APPROVED)
        self.assertEqual(item1.reviewed_by, self.user)
        self.assertEqual(item2.reviewed_by, self.user)
        self.assertIsNotNone(item1.reviewed_at)
        self.assertIsNotNone(item2.reviewed_at)

    def test_bulk_approve_empty_ids(self):
        """Test bulk approve with empty ID list."""
        response = self.client.post(
            "/api/ai_review/bulk-approve/",
            {"ids": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_approve_nonexistent_ids(self):
        """Test bulk approve with nonexistent IDs."""
        response = self.client.post(
            "/api/ai_review/bulk-approve/",
            {"ids": [9999]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should approve 0 items
        self.assertIn("Approved 0 AI review items", response.json()["detail"])

    def test_bulk_reject(self):
        """Test bulk reject functionality."""
        document2 = DocumentFactory.create(owner=self.user)
        item1 = AIReviewQueueFactory.create(document=self.document)
        item2 = AIReviewQueueFactory.create(document=document2)

        response = self.client.post(
            "/api/ai_review/bulk-reject/",
            {"ids": [item1.id, item2.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Refresh from database
        item1.refresh_from_db()
        item2.refresh_from_db()

        self.assertEqual(item1.status, AIReviewQueue.Status.REJECTED)
        self.assertEqual(item2.status, AIReviewQueue.Status.REJECTED)
        self.assertEqual(item1.reviewed_by, self.user)
        self.assertEqual(item2.reviewed_by, self.user)

    def test_bulk_actions_permission_check(self):
        """Test that bulk actions check permissions."""
        # Create item for other user
        other_item = AIReviewQueueFactory.create(document=self.other_document)

        # Try to approve other user's item
        response = self.client.post(
            "/api/ai_review/bulk-approve/",
            {"ids": [other_item.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_serializer_fields(self):
        """Test that serializer includes all expected fields."""
        item = AIReviewQueueFactory.create(document=self.document)
        serializer = AIReviewQueueSerializer(item, all_fields=True)

        data = serializer.data
        expected_fields = [
            "id",
            "document",
            "suggestions",
            "confidence_scores",
            "status",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
            "owner",
            "permissions",
            "user_can_change",
            "is_shared_by_requester",
        ]

        for field in expected_fields:
            self.assertIn(field, data)


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


class AISuggestionHistoryTestCase(TestCase):
    """Test cases for AISuggestionHistory model."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.document = DocumentFactory.create(owner=self.user)

    def test_str_method(self):
        """Test string representation of AISuggestionHistory."""
        history = AISuggestionHistoryFactory.create(document=self.document)
        expected = f"AI Suggestion History for {self.document.title} (Applied)"
        self.assertEqual(str(history), expected)

        # Test rolled back
        history.rolled_back = True
        history.save()
        expected_rolled_back = (
            f"AI Suggestion History for {self.document.title} (Rolled Back)"
        )
        self.assertEqual(str(history), expected_rolled_back)

    def test_ordering(self):
        """Test that items are ordered by applied_at descending."""
        history1 = AISuggestionHistoryFactory.create(document=self.document)
        history2 = AISuggestionHistoryFactory.create(document=self.document)

        items = list(AISuggestionHistory.objects.all())
        self.assertEqual(items[0], history2)  # Most recent first
        self.assertEqual(items[1], history1)
