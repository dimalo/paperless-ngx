from unittest.mock import patch

from django.test import TestCase

from documents.parsers import DocumentParser
from documents.parsers import get_parser_class_for_mime_type
from paperless.models import ApplicationConfiguration


class MockParser1(DocumentParser):
    def get_settings(self):
        return None

    def parse(self, p, m):
        pass

    def get_thumbnail(self, p, m):
        pass


class MockParser2(DocumentParser):
    def get_settings(self):
        return None

    def parse(self, p, m):
        pass

    def get_thumbnail(self, p, m):
        pass


class TestOCRBroker(TestCase):
    def setUp(self):
        self.config, _ = ApplicationConfiguration.objects.get_or_create(pk=1)

    @patch("documents.parsers.document_consumer_declaration")
    def test_broker_priority(self, mock_signal):
        # Mock two registered parsers
        mock_signal.send.return_value = [
            (
                None,
                {
                    "parser": MockParser1,
                    "weight": 0,
                    "engine_id": "engine1",
                    "mime_types": {"image/png": ".png"},
                },
            ),
            (
                None,
                {
                    "parser": MockParser2,
                    "weight": 0,
                    "engine_id": "engine2",
                    "mime_types": {"image/png": ".png"},
                },
            ),
        ]

        # 1. Test global priority: engine2 first
        self.config.ocr_engine_priority = "engine2,engine1"
        self.config.save()

        parser = get_parser_class_for_mime_type("image/png")
        self.assertEqual(parser, MockParser2)

        # 2. Test global priority: engine1 first
        self.config.ocr_engine_priority = "engine1,engine2"
        self.config.save()

        parser = get_parser_class_for_mime_type("image/png")
        self.assertEqual(parser, MockParser1)

        # 3. Test workflow override: force engine2 regardless of global priority
        parser = get_parser_class_for_mime_type("image/png", preferred_engine="engine2")
        self.assertEqual(parser, MockParser2)

    @patch("documents.parsers.document_consumer_declaration")
    def test_broker_fallback(self, mock_signal):
        mock_signal.send.return_value = [
            (
                None,
                {
                    "parser": MockParser1,
                    "weight": 10,
                    "mime_types": {"image/png": ".png"},
                },
            ),
            (
                None,
                {
                    "parser": MockParser2,
                    "weight": 20,
                    "engine_id": "engine2",
                    "mime_types": {"image/png": ".png"},
                },
            ),
        ]

        # Priority list doesn't mention engine2, so weights should decide
        self.config.ocr_engine_priority = (
            "engine1"  # engine1 doesn't exist as engine_id
        )
        self.config.save()

        parser = get_parser_class_for_mime_type("image/png")
        self.assertEqual(
            parser,
            MockParser2,
        )  # MockParser2 has higher weight (20 vs 10)
