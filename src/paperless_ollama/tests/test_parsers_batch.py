import uuid
from pathlib import Path
from unittest import mock

import litellm
from django.test import TestCase

from paperless_ollama.parsers import OllamaDocumentParser


class TestOllamaParserBatching(TestCase):
    def setUp(self):
        self.parser = OllamaDocumentParser(uuid.uuid4())

    @mock.patch("paperless_ollama.parsers.OllamaDocumentParser._prepare_message")
    @mock.patch("litellm.batch_completion")
    @mock.patch(
        "paperless_ollama.parsers.OllamaDocumentParser._convert_pdf_pages_to_images",
    )
    def test_parse_pdf_batching(self, mock_convert, mock_batch, mock_prepare):
        """
        Test that PDF pages are processed in batches of 4.
        """
        # 6 pages = 2 batches (4 + 2)
        mock_convert.return_value = [Path(f"page-{i}.png") for i in range(1, 7)]
        mock_prepare.return_value = ({"role": "user"}, 800, 600)

        mock_resp = mock.Mock()
        mock_resp.choices = [mock.Mock(message=mock.Mock(content="text"))]
        mock_batch.return_value = [mock_resp] * 4  # First batch

        def batch_side_effect(model, messages, **kwargs):
            return [mock_resp] * len(messages)

        mock_batch.side_effect = batch_side_effect

        with (
            mock.patch("pikepdf.Pdf.new"),
            mock.patch("pikepdf.Pdf.open"),
            mock.patch("pathlib.Path.exists", return_value=True),
        ):
            self.parser.parse(Path("test.pdf"), "application/pdf")

        # Check number of batch calls
        self.assertEqual(mock_batch.call_count, 2)
        # First call should have 4 messages
        self.assertEqual(len(mock_batch.call_args_list[0][1]["messages"]), 4)
        # Second call should have 2 messages
        self.assertEqual(len(mock_batch.call_args_list[1][1]["messages"]), 2)

    @mock.patch("litellm.completion")
    def test_retry_logic_sequential(self, mock_completion):
        """
        Test that sequential calls retry on timeout.
        """
        # Fail twice, then succeed
        mock_completion.side_effect = [
            litellm.Timeout("timeout", model="model", llm_provider="ollama"),
            litellm.Timeout("timeout", model="model", llm_provider="ollama"),
            mock.Mock(choices=[mock.Mock(message=mock.Mock(content="success"))]),
        ]

        with mock.patch("time.sleep"):  # Don't actually sleep
            result = self.parser._call_ollama_api_sequential([{"role": "user"}])

        self.assertEqual(result, "success")
        self.assertEqual(mock_completion.call_count, 3)

    @mock.patch("litellm.completion")
    def test_retry_logic_sequential_fails_after_max(self, mock_completion):
        """
        Test that sequential calls fail after 2 retries (3 total attempts).
        """
        mock_completion.side_effect = litellm.Timeout(
            "timeout",
            model="model",
            llm_provider="ollama",
        )

        with mock.patch("time.sleep"):
            with self.assertRaises(litellm.Timeout):
                self.parser._call_ollama_api_sequential([{"role": "user"}])

        self.assertEqual(mock_completion.call_count, 3)

    @mock.patch("litellm.batch_completion")
    def test_retry_logic_batch(self, mock_batch):
        """
        Test that batch calls retry on failure.
        """
        mock_resp = mock.Mock()
        mock_resp.choices = [mock.Mock(message=mock.Mock(content="success"))]

        mock_batch.side_effect = [
            Exception("Batch failed"),
            [mock_resp, mock_resp],
        ]

        with mock.patch("time.sleep"):
            results = self.parser._call_ollama_api_batch(
                [[{"role": "user"}], [{"role": "user"}]],
            )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], "success")
        self.assertEqual(mock_batch.call_count, 2)
