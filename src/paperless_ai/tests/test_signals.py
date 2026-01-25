from unittest.mock import patch

import pytest

from paperless.models import ApplicationConfiguration


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
