from unittest import mock

import litellm
import pytest
from django.test import TestCase

from paperless_ai.embedding import LiteLLMEmbedding


class TestLiteLLMEmbeddingBatching(TestCase):
    def setUp(self):
        self.embedding = LiteLLMEmbedding(model_name="nomic-embed-text")

    @mock.patch("litellm.embedding")
    def test_get_text_embeddings_batching(self, mock_embedding):
        """
        Test that embeddings are processed in parallel batches of 4.
        """
        # 6 texts = 2 batches (4 + 2)
        texts = [f"text-{i}" for i in range(1, 7)]

        mock_resp = mock.Mock()
        mock_resp.data = [{"embedding": [0.1]}]

        def embedding_side_effect(model, input, **kwargs):
            resp = mock.Mock()
            resp.data = [{"embedding": [0.1]} for _ in input]
            return resp

        mock_embedding.side_effect = embedding_side_effect

        results = self.embedding._get_text_embeddings(texts)

        self.assertEqual(len(results), 6)
        # Should be called twice (batches of 4 and 2)
        self.assertEqual(mock_embedding.call_count, 2)
        # First call should have 4 inputs
        self.assertEqual(len(mock_embedding.call_args_list[0][1]["input"]), 4)
        # Second call should have 2 inputs
        self.assertEqual(len(mock_embedding.call_args_list[1][1]["input"]), 2)

    @mock.patch("litellm.aembedding")
    @pytest.mark.asyncio
    async def test_aget_text_embeddings_batching(self, mock_aembedding):
        """
        Test that async embeddings are processed in parallel batches of 4.
        """
        texts = [f"text-{i}" for i in range(1, 7)]

        async def aembedding_side_effect(model, input, **kwargs):
            resp = mock.Mock()
            resp.data = [{"embedding": [0.1]} for _ in input]
            return resp

        mock_aembedding.side_effect = aembedding_side_effect

        results = await self.embedding._aget_text_embeddings(texts)

        self.assertEqual(len(results), 6)
        self.assertEqual(mock_aembedding.call_count, 2)

    @mock.patch("litellm.embedding")
    def test_retry_logic_sequential(self, mock_embedding):
        """
        Test that sequential embedding calls retry on timeout.
        """
        mock_embedding.side_effect = [
            litellm.Timeout("timeout", model="model", llm_provider="ollama"),
            litellm.Timeout("timeout", model="model", llm_provider="ollama"),
            mock.Mock(data=[{"embedding": [0.2]}]),
        ]

        with mock.patch("time.sleep"):
            result = self.embedding._get_text_embedding("test")

        self.assertEqual(result, [0.2])
        self.assertEqual(mock_embedding.call_count, 3)

    @mock.patch("litellm.aembedding")
    @pytest.mark.asyncio
    async def test_retry_logic_async(self, mock_aembedding):
        """
        Test that async embedding calls retry on timeout.
        """

        async def side_effect(*args, **kwargs):
            if mock_aembedding.call_count < 3:
                raise litellm.Timeout("timeout", model="model", llm_provider="ollama")
            resp = mock.Mock()
            resp.data = [{"embedding": [0.3]}]
            return resp

        mock_aembedding.side_effect = side_effect

        with mock.patch("asyncio.sleep"):
            result = await self.embedding._aget_text_embedding("test")

        self.assertEqual(result, [0.3])
        self.assertEqual(mock_aembedding.call_count, 3)
