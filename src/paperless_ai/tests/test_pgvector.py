from unittest.mock import patch

import pytest

from paperless_ai.vector_store import VectorStoreFactory


@pytest.mark.django_db
class TestVectorStoreFactory:
    @patch("paperless_ai.vector_store.AIConfig")
    def test_get_vector_store_backend_explicit_faiss(self, mock_config):
        mock_config.return_value.vector_store_backend = "faiss"
        assert VectorStoreFactory.get_vector_store_backend() == "faiss"

    @patch("paperless_ai.vector_store.AIConfig")
    def test_get_vector_store_backend_explicit_postgres(self, mock_config):
        mock_config.return_value.vector_store_backend = "postgres"
        assert VectorStoreFactory.get_vector_store_backend() == "postgres"

    @patch("paperless_ai.vector_store.VectorStoreFactory._is_pgvector_available")
    @patch("paperless_ai.vector_store.AIConfig")
    def test_get_vector_store_backend_auto_fallback(self, mock_config, mock_available):
        mock_config.return_value.vector_store_backend = "auto"
        mock_available.return_value = False
        assert VectorStoreFactory.get_vector_store_backend() == "faiss"

    @patch("paperless_ai.vector_store.VectorStoreFactory._is_pgvector_available")
    @patch("paperless_ai.vector_store.AIConfig")
    def test_get_vector_store_backend_auto_success(self, mock_config, mock_available):
        mock_config.return_value.vector_store_backend = "auto"
        mock_available.return_value = True
        assert VectorStoreFactory.get_vector_store_backend() == "postgres"

    @patch("django.db.connection.cursor")
    def test_is_pgvector_available_success(self, mock_cursor):
        with patch(
            "django.conf.settings.DATABASES",
            {"default": {"ENGINE": "django.db.backends.postgresql"}},
        ):
            mock_cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
            assert VectorStoreFactory._is_pgvector_available() is True

    @patch("django.db.connection.cursor")
    def test_is_pgvector_available_missing_extension(self, mock_cursor):
        with patch(
            "django.conf.settings.DATABASES",
            {"default": {"ENGINE": "django.db.backends.postgresql"}},
        ):
            mock_cursor.return_value.__enter__.return_value.fetchone.return_value = None
            assert VectorStoreFactory._is_pgvector_available() is False

    @patch("paperless_ai.vector_store.VectorStoreFactory._get_postgres_storage_context")
    @patch("paperless_ai.vector_store.VectorStoreFactory.get_vector_store_backend")
    def test_get_storage_context_postgres(self, mock_backend, mock_pg_context):
        mock_backend.return_value = "postgres"
        VectorStoreFactory.get_storage_context()
        mock_pg_context.assert_called_once()

    @patch("paperless_ai.vector_store.VectorStoreFactory._get_faiss_storage_context")
    @patch("paperless_ai.vector_store.VectorStoreFactory.get_vector_store_backend")
    def test_get_storage_context_faiss(self, mock_backend, mock_faiss_context):
        mock_backend.return_value = "faiss"
        VectorStoreFactory.get_storage_context(rebuild=True)
        mock_faiss_context.assert_called_once_with(rebuild=True)

    @patch("llama_index.vector_stores.postgres.PGVectorStore")
    @patch("paperless_ai.embedding.get_embedding_dim")
    @patch("paperless_ai.vector_store.AIConfig")
    def test_get_postgres_storage_context_overrides(
        self,
        mock_config,
        mock_dim,
        mock_pg_store,
    ):
        mock_dim.return_value = 1536
        cfg = mock_config.return_value
        cfg.vector_store_host = "custom-host"
        cfg.vector_store_port = 9999
        cfg.vector_store_name = "custom-db"
        cfg.vector_store_user = "custom-user"
        cfg.vector_store_pass = "custom-pass"

        VectorStoreFactory._get_postgres_storage_context()
        mock_pg_store.assert_called_once_with(
            connection_string="postgresql://custom-user:custom-pass@custom-host:9999/custom-db",
            table_name="paperless_vectors",
            embed_dim=1536,
        )

    @patch("llama_index.vector_stores.postgres.PGVectorStore")
    @patch("paperless_ai.embedding.get_embedding_dim")
    @patch("paperless_ai.vector_store.AIConfig")
    def test_get_postgres_storage_context_defaults(
        self,
        mock_config,
        mock_dim,
        mock_pg_store,
    ):
        mock_dim.return_value = 768
        cfg = mock_config.return_value
        cfg.vector_store_host = None
        cfg.vector_store_port = None
        cfg.vector_store_user = None
        cfg.vector_store_pass = None
        cfg.vector_store_name = None

        with patch(
            "django.conf.settings.DATABASES",
            {
                "default": {
                    "NAME": "paperless_main",
                    "HOST": "main-host",
                    "PORT": 5432,
                    "USER": "main-user",
                    "PASSWORD": "main-pass",
                },
            },
        ):
            VectorStoreFactory._get_postgres_storage_context()
            mock_pg_store.assert_called_once_with(
                connection_string="postgresql://main-user:main-pass@main-host:5432/paperless_main",
                table_name="paperless_vectors",
                embed_dim=768,
            )
