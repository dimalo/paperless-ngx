from unittest import TestCase
from unittest import mock

import pytest

from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration


@pytest.mark.django_db
@mock.patch("documents.tasks.llmindex_index.delay")
class TestAIConfig(TestCase):
    def setUp(self):
        # Ensure we start with a clean state for singletons or cached properties if any
        ApplicationConfiguration.objects.all().delete()

    def test_no_endpoint_no_fallback(self, mock_delay):
        """
        GIVEN:
            - AI backend is ollama
            - llm_endpoint is unset
        WHEN:
            - AIConfig is initialized
        THEN:
            - llm_endpoint remains None
        """
        ApplicationConfiguration.objects.create(
            ai_enabled=True,
            llm_backend="ollama",
            llm_endpoint="",
        )

        ai_config = AIConfig()
        self.assertIsNone(ai_config.llm_endpoint)

    def test_endpoint_used_when_set(self, mock_delay):
        """
        GIVEN:
            - AI backend is ollama
            - llm_endpoint IS set
        WHEN:
            - AIConfig is initialized
        THEN:
            - llm_endpoint is used as-is
        """
        ApplicationConfiguration.objects.create(
            ai_enabled=True,
            llm_backend="ollama",
            llm_endpoint="http://custom-ai:11434",
        )

        ai_config = AIConfig()
        self.assertEqual(ai_config.llm_endpoint, "http://custom-ai:11434")

    def test_no_endpoint_for_other_backends(self, mock_delay):
        """
        GIVEN:
            - AI backend is openai
            - llm_endpoint is unset
        WHEN:
            - AIConfig is initialized
        THEN:
            - llm_endpoint remains None
        """
        ApplicationConfiguration.objects.create(
            ai_enabled=True,
            llm_backend="openai",
            llm_endpoint="",
        )

        ai_config = AIConfig()
        self.assertIsNone(ai_config.llm_endpoint)

    def test_endpoint_from_settings(self, mock_delay):
        """
        GIVEN:
            - AI backend is ollama
            - llm_endpoint unset in DB
            - PAPERLESS_LLM_ENDPOINT set in env
        WHEN:
            - AIConfig is initialized
        THEN:
            - llm_endpoint uses env var LLM_ENDPOINT
        """
        ApplicationConfiguration.objects.create(
            ai_enabled=True,
            llm_backend="ollama",
            llm_endpoint="",
        )

        with mock.patch(
            "django.conf.settings.LLM_ENDPOINT",
            "http://env-ollama:11434",
        ):
            ai_config = AIConfig()
            self.assertEqual(ai_config.llm_endpoint, "http://env-ollama:11434")
