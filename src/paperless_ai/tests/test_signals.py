from unittest.mock import patch

import pytest
from django.core.cache import cache

from documents.models import Correspondent
from documents.models import DocumentType
from documents.models import Tag
from paperless.models import ApplicationConfiguration
from paperless_ai.ai_classifier import CACHE_KEY_CORRESPONDENTS
from paperless_ai.ai_classifier import CACHE_KEY_DOC_TYPES
from paperless_ai.ai_classifier import CACHE_KEY_TAGS


@pytest.mark.django_db
class TestAISignals:
    @patch("paperless_ai.signals.llmindex_index.delay")
    def test_rebuild_triggered_on_relevant_change(self, mock_delay):
        """
        Test that a rebuild is triggered when a relevant setting changes.
        """
        config, _ = ApplicationConfiguration.objects.get_or_create(
            defaults={"ai_enabled": True},
        )
        # Ensure it's in a known state
        config.ai_enabled = True
        config.vector_store_backend = "auto"
        config.save()

        # Reset mock after setup
        mock_delay.reset_mock()

        # Change a relevant setting
        config.vector_store_backend = "faiss"
        config.save()

        assert mock_delay.called
        assert mock_delay.call_args[1]["rebuild"] is True

    @patch("paperless_ai.signals.llmindex_index.delay")
    def test_rebuild_not_triggered_on_irrelevant_change(self, mock_delay):
        """
        Test that a rebuild is NOT triggered when an irrelevant setting changes.
        """
        config, _ = ApplicationConfiguration.objects.get_or_create(
            defaults={"ai_enabled": True},
        )
        config.ai_enabled = True
        config.app_title = "Original"
        config.save()

        # Reset mock after setup
        mock_delay.reset_mock()

        # Change an irrelevant setting
        config.app_title = "New Title"
        config.save()

        assert not mock_delay.called

    @patch("paperless_ai.signals.llmindex_index.delay")
    def test_rebuild_triggered_on_ai_enabled(self, mock_delay):
        """
        Test that a rebuild is triggered when AI is enabled.
        """
        config, _ = ApplicationConfiguration.objects.get_or_create(
            defaults={"ai_enabled": False},
        )
        config.ai_enabled = False
        config.save()

        mock_delay.reset_mock()

        config.ai_enabled = True
        config.save()

        assert mock_delay.called


@pytest.mark.django_db
class TestCacheInvalidationSignals:
    """Test that cache is invalidated when models change."""

    def setup_method(self):
        """Clear cache before each test."""
        cache.clear()

    def test_tag_save_invalidates_cache(self):
        """Test that saving a tag clears the tags cache."""
        cache.set(CACHE_KEY_TAGS, "CachedTag1, CachedTag2")
        assert cache.get(CACHE_KEY_TAGS) is not None

        Tag.objects.create(name="NewTag")

        assert cache.get(CACHE_KEY_TAGS) is None

    def test_tag_delete_invalidates_cache(self):
        """Test that deleting a tag clears the tags cache."""
        tag = Tag.objects.create(name="TagToDelete")
        cache.set(CACHE_KEY_TAGS, "CachedTag1, CachedTag2")
        assert cache.get(CACHE_KEY_TAGS) is not None

        tag.delete()

        assert cache.get(CACHE_KEY_TAGS) is None

    def test_tag_update_invalidates_cache(self):
        """Test that updating a tag clears the tags cache."""
        tag = Tag.objects.create(name="OldName")
        cache.set(CACHE_KEY_TAGS, "CachedTag1, CachedTag2")
        assert cache.get(CACHE_KEY_TAGS) is not None

        tag.name = "NewName"
        tag.save()

        assert cache.get(CACHE_KEY_TAGS) is None

    def test_document_type_save_invalidates_cache(self):
        """Test that saving a document type clears the document types cache."""
        cache.set(CACHE_KEY_DOC_TYPES, "CachedType1, CachedType2")
        assert cache.get(CACHE_KEY_DOC_TYPES) is not None

        DocumentType.objects.create(name="NewType")

        assert cache.get(CACHE_KEY_DOC_TYPES) is None

    def test_document_type_delete_invalidates_cache(self):
        """Test that deleting a document type clears the document types cache."""
        doc_type = DocumentType.objects.create(name="TypeToDelete")
        cache.set(CACHE_KEY_DOC_TYPES, "CachedType1, CachedType2")
        assert cache.get(CACHE_KEY_DOC_TYPES) is not None

        doc_type.delete()

        assert cache.get(CACHE_KEY_DOC_TYPES) is None

    def test_document_type_update_invalidates_cache(self):
        """Test that updating a document type clears the document types cache."""
        doc_type = DocumentType.objects.create(name="OldType")
        cache.set(CACHE_KEY_DOC_TYPES, "CachedType1, CachedType2")
        assert cache.get(CACHE_KEY_DOC_TYPES) is not None

        doc_type.name = "NewType"
        doc_type.save()

        assert cache.get(CACHE_KEY_DOC_TYPES) is None

    def test_correspondent_save_invalidates_cache(self):
        """Test that saving a correspondent clears the correspondents cache."""
        cache.set(CACHE_KEY_CORRESPONDENTS, "CachedCorr1, CachedCorr2")
        assert cache.get(CACHE_KEY_CORRESPONDENTS) is not None

        Correspondent.objects.create(name="NewCorrespondent")

        assert cache.get(CACHE_KEY_CORRESPONDENTS) is None

    def test_correspondent_delete_invalidates_cache(self):
        """Test that deleting a correspondent clears the correspondents cache."""
        correspondent = Correspondent.objects.create(name="CorrToDelete")
        cache.set(CACHE_KEY_CORRESPONDENTS, "CachedCorr1, CachedCorr2")
        assert cache.get(CACHE_KEY_CORRESPONDENTS) is not None

        correspondent.delete()

        assert cache.get(CACHE_KEY_CORRESPONDENTS) is None

    def test_correspondent_update_invalidates_cache(self):
        """Test that updating a correspondent clears the correspondents cache."""
        correspondent = Correspondent.objects.create(name="OldCorr")
        cache.set(CACHE_KEY_CORRESPONDENTS, "CachedCorr1, CachedCorr2")
        assert cache.get(CACHE_KEY_CORRESPONDENTS) is not None

        correspondent.name = "NewCorr"
        correspondent.save()

        assert cache.get(CACHE_KEY_CORRESPONDENTS) is None

    def test_other_caches_not_affected_by_tag_changes(self):
        """Test that tag changes only invalidate tag cache, not others."""
        cache.set(CACHE_KEY_TAGS, "CachedTags")
        cache.set(CACHE_KEY_DOC_TYPES, "CachedTypes")
        cache.set(CACHE_KEY_CORRESPONDENTS, "CachedCorrs")

        Tag.objects.create(name="NewTag")

        assert cache.get(CACHE_KEY_TAGS) is None
        assert cache.get(CACHE_KEY_DOC_TYPES) == "CachedTypes"
        assert cache.get(CACHE_KEY_CORRESPONDENTS) == "CachedCorrs"
