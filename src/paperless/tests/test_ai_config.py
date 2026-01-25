from unittest import TestCase
from unittest import mock

import pytest

from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration


@pytest.mark.django_db
class TestAIConfig(TestCase):
    def setUp(self):
        # Ensure we start with a clean state for singletons or cached properties if any
        ApplicationConfiguration.objects.all().delete()

    def test_fallback_to_ollama_endpoint(self):
        """
        GIVEN:
            - AI backend is ollama
            - llm_endpoint is unset
            - ollama_endpoint is set (simulating OCR config)
        WHEN:
            - AIConfig is initialized
        THEN:
            - llm_endpoint falls back to ollama_endpoint
        """
        ApplicationConfiguration.objects.create(
            ai_enabled=True,
            llm_backend="ollama",
            llm_endpoint="",
            ollama_endpoint="http://example-ollama:11434",
        )

        ai_config = AIConfig()
        self.assertEqual(ai_config.llm_endpoint, "http://example-ollama:11434")

    def test_no_fallback_if_endpoint_set(self):
        """
        GIVEN:
            - AI backend is ollama
            - llm_endpoint IS set
            - ollama_endpoint is different
        WHEN:
            - AIConfig is initialized
        THEN:
            - llm_endpoint is used as-is
        """
        ApplicationConfiguration.objects.create(
            ai_enabled=True,
            llm_backend="ollama",
            llm_endpoint="http://custom-ai:11434",
            ollama_endpoint="http://ocr-ollama:11434",
        )

        ai_config = AIConfig()
        self.assertEqual(ai_config.llm_endpoint, "http://custom-ai:11434")

    def test_no_fallback_for_other_backends(self):
        """
        GIVEN:
            - AI backend is openai
            - llm_endpoint is unset
            - ollama_endpoint is set
        WHEN:
            - AIConfig is initialized
        THEN:
            - llm_endpoint remains None (no fallback)
        """
        ApplicationConfiguration.objects.create(
            ai_enabled=True,
            llm_backend="openai",
            llm_endpoint="",
            ollama_endpoint="http://example-ollama:11434",
        )

        ai_config = AIConfig()
        self.assertIsNone(ai_config.llm_endpoint)

    def test_fallback_from_settings(self):
        """
        GIVEN:
            - AI backend is ollama
            - llm_endpoint unset in DB
            - ollama_endpoint unset in DB
            - PAPERLESS_OLLAMA_ENDPOINT set in env
        WHEN:
            - AIConfig is initialized
        THEN:
            - llm_endpoint falls back to env var OLLAMA_ENDPOINT
        """
        ApplicationConfiguration.objects.create(
            ai_enabled=True,
            llm_backend="ollama",
            llm_endpoint="",
            ollama_endpoint="",
        )

        with mock.patch.dict(
            "os.environ",
            {"PAPERLESS_OLLAMA_ENDPOINT": "http://env-ollama:11434"},
        ):
            # Force reload settings if needed, but config.py accesses settings.SOME_VAL which
            # usually reflects os.environ at import time or access time.
            # paperless.settings usually reads env vars at module level.
            # However, config.py uses getattr(settings, "OLLAMA_ENDPOINT")
            # so we need to patch settings object, NOT os.environ directly if settings are already loaded.

            with mock.patch(
                "django.conf.settings.OLLAMA_ENDPOINT",
                "http://env-ollama:11434",
            ):
                ai_config = AIConfig()
                self.assertEqual(ai_config.llm_endpoint, "http://env-ollama:11434")
