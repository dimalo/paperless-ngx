import logging
import urllib.parse

from django.conf import settings
from llama_index.core import StorageContext
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.storage.index_store import SimpleIndexStore
from llama_index.vector_stores.faiss import FaissVectorStore
from llama_index.vector_stores.postgres import PGVectorStore

from paperless.config import AIConfig

logger = logging.getLogger("paperless_ai.vector_store")


class VectorStoreFactory:
    """
    Factory class to create and configure the appropriate vector store
    based on the application settings and environment.
    """

    @staticmethod
    def get_vector_store_backend() -> str:
        """
        Determines which vector store backend to use.
        """
        config = AIConfig()
        backend = config.vector_store_backend

        if backend == "auto":
            if VectorStoreFactory._is_pgvector_available():
                return "postgres"
            return "faiss"

        return backend

    @staticmethod
    def _is_pgvector_available() -> bool:
        """
        Checks if the Postgres database engine is in use and if the
        pgvector extension is installed.
        """
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
            return False

        try:
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'",
                )
                return cursor.fetchone() is not None
        except Exception as e:
            logger.debug("Failed to check for pgvector extension: %s", e)
            return False

    @staticmethod
    def get_storage_context(*, rebuild: bool = False) -> StorageContext:
        """
        Returns the appropriate StorageContext for the selected backend.
        """
        backend = VectorStoreFactory.get_vector_store_backend()

        if backend == "postgres":
            return VectorStoreFactory._get_postgres_storage_context()
        else:
            return VectorStoreFactory._get_faiss_storage_context(rebuild=rebuild)

    @staticmethod
    def _get_postgres_storage_context() -> StorageContext:
        """
        Initializes and returns a StorageContext using PostgresVectorStore.
        """

        config = AIConfig()
        db_settings = settings.DATABASES["default"]

        host = config.vector_store_host or db_settings.get("HOST", "localhost")
        port = config.vector_store_port or db_settings.get("PORT", "5432")
        user = config.vector_store_user or db_settings.get("USER", "paperless")
        password = config.vector_store_pass or db_settings.get("PASSWORD", "paperless")

        # Database name logic: use override or <main-db>-vector
        db_name = config.vector_store_name or db_settings.get("NAME", "paperless")

        password = urllib.parse.quote_plus(str(password))
        connection_string = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

        from paperless_ai.embedding import get_embedding_dim

        embed_dim = get_embedding_dim()

        vector_store = PGVectorStore(
            connection_string=connection_string,
            table_name="paperless_vectors",
            embed_dim=embed_dim,
        )

        return StorageContext.from_defaults(vector_store=vector_store)

    @staticmethod
    def _get_faiss_storage_context(*, rebuild: bool = False) -> StorageContext:
        """
        Initializes and returns a StorageContext using FaissVectorStore (local JSON).
        """
        import shutil

        import faiss

        if rebuild:
            shutil.rmtree(settings.LLM_INDEX_DIR, ignore_errors=True)
            settings.LLM_INDEX_DIR.mkdir(parents=True, exist_ok=True)

        if rebuild or not settings.LLM_INDEX_DIR.exists():
            from paperless_ai.embedding import get_embedding_dim

            embedding_dim = get_embedding_dim()
            faiss_index = faiss.IndexFlatL2(embedding_dim)
            vector_store = FaissVectorStore(faiss_index=faiss_index)
            docstore = SimpleDocumentStore()
            index_store = SimpleIndexStore()
        else:
            vector_store = FaissVectorStore.from_persist_dir(settings.LLM_INDEX_DIR)
            docstore = SimpleDocumentStore.from_persist_dir(settings.LLM_INDEX_DIR)
            index_store = SimpleIndexStore.from_persist_dir(settings.LLM_INDEX_DIR)

        return StorageContext.from_defaults(
            docstore=docstore,
            index_store=index_store,
            vector_store=vector_store,
            persist_dir=settings.LLM_INDEX_DIR,
        )
