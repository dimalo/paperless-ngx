import logging
from datetime import timedelta
from pathlib import Path
from typing import cast

import llama_index.core.settings as llama_settings
from celery import states
from django.conf import settings
from django.utils import timezone
from llama_index.core import Document as LlamaDocument
from llama_index.core import VectorStoreIndex
from llama_index.core import load_index_from_storage
from llama_index.core.node_parser import SimpleNodeParser
from llama_index.core.schema import BaseNode
from llama_index.core.text_splitter import TokenTextSplitter
from llama_index.core.vector_stores import FilterCondition
from llama_index.core.vector_stores import MetadataFilter
from llama_index.core.vector_stores import MetadataFilters
from tqdm import tqdm

from documents.models import Document
from documents.models import PaperlessTask
from paperless_ai.embedding import build_llm_index_text
from paperless_ai.embedding import get_embedding_model
from paperless_ai.vector_store import VectorStoreFactory

logger = logging.getLogger("paperless_ai.indexing")


def queue_llm_index_update_if_needed(*, rebuild: bool, reason: str) -> bool:
    from documents.tasks import llmindex_index

    has_running = PaperlessTask.objects.filter(
        task_name=PaperlessTask.TaskName.LLMINDEX_UPDATE,
        status__in=[states.PENDING, states.STARTED],
    ).exists()
    has_recent = PaperlessTask.objects.filter(
        task_name=PaperlessTask.TaskName.LLMINDEX_UPDATE,
        date_created__gte=(timezone.now() - timedelta(minutes=5)),
    ).exists()
    if has_running or has_recent:
        return False

    llmindex_index.delay(rebuild=rebuild, scheduled=False, auto=True)
    logger.warning(
        "Queued LLM index update%s: %s",
        " (rebuild)" if rebuild else "",
        reason,
    )
    return True


def get_or_create_storage_context(*, rebuild=False):
    """
    Loads or creates the StorageContext using VectorStoreFactory.
    """
    return VectorStoreFactory.get_storage_context(rebuild=rebuild)


def build_document_node(document: Document) -> list[BaseNode]:
    text = build_llm_index_text(document)
    metadata = {
        "document_id": str(document.pk),
        "title": document.title,
        "tags": [t.name for t in document.tags.all()],  # type: ignore
        "correspondent": document.correspondent.name
        if document.correspondent
        else None,
        "document_type": document.document_type.name
        if document.document_type
        else None,
        "created": document.created.isoformat() if document.created else None,  # type: ignore
        "added": document.added.isoformat() if document.added else None,  # type: ignore
        "modified": document.modified.isoformat(),  # type: ignore
    }
    doc = LlamaDocument(text=text, metadata=metadata)
    doc.id_ = str(document.pk)
    parser = SimpleNodeParser()
    return parser.get_nodes_from_documents([doc])


def load_or_build_index(nodes=None) -> VectorStoreIndex:
    """
    Load an existing VectorStoreIndex if present,
    or build a new one using provided nodes if storage is empty.
    """
    embed_model = get_embedding_model()
    llama_settings.Settings.embed_model = embed_model
    storage_context = get_or_create_storage_context()

    if VectorStoreFactory.get_vector_store_backend() == "postgres":
        return VectorStoreIndex.from_vector_store(
            vector_store=storage_context.vector_store,
            embed_model=embed_model,
        )

    try:
        return cast(
            "VectorStoreIndex",
            load_index_from_storage(storage_context=storage_context),
        )
    except Exception as e:
        logger.warning("Failed to load index from storage: %s", e)
        if not nodes:
            queue_llm_index_update_if_needed(
                rebuild=vector_store_file_exists(),
                reason="LLM index missing or invalid while loading.",
            )
            raise
        return VectorStoreIndex(
            nodes=nodes or [],
            storage_context=storage_context,
            embed_model=embed_model,
        )


def remove_document_from_index(document: Document, index: VectorStoreIndex):
    """
    Removes a document from the index, handling backend specifics.
    """
    if VectorStoreFactory.get_vector_store_backend() == "postgres":
        try:
            # Delete by ref_doc_id (which we set to document.pk)
            index.delete_ref_doc(str(document.pk), delete_from_docstore=False)
        except Exception as e:
            logger.debug("Failed to delete document %s from index: %s", document.pk, e)
    else:
        # FAISS / Local Logic
        all_node_ids = list(index.docstore.docs.keys())
        existing_nodes = [
            node.node_id
            for node in index.docstore.get_nodes(all_node_ids)
            if node.metadata.get("document_id") == str(document.pk)
        ]
        for node_id in existing_nodes:
            index.docstore.delete_document(node_id)


def vector_store_file_exists():
    """
    Check if the vector store file exists in the LLM index directory.
    For Postgres, returns True to ensure we use the incremental update path.
    """
    if VectorStoreFactory.get_vector_store_backend() == "postgres":
        return True
    return Path(settings.LLM_INDEX_DIR / "docstore.json").exists()


def get_existing_docs_map(index: VectorStoreIndex) -> dict[str, str]:
    """
    Returns a map of document_id -> modified_iso for documents currently in the index.
    """
    existing_map = {}
    if VectorStoreFactory.get_vector_store_backend() == "postgres":
        from django.db import connection

        with connection.cursor() as cursor:
            # Try to find the table name ('paperless_vectors')
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name = 'paperless_vectors'",
            )
            rows = cursor.fetchall()
            if rows:
                table_name = "paperless_vectors"
                try:
                    cursor.execute(
                        f"SELECT cmetadata->>'document_id', cmetadata->>'modified' FROM {table_name}",
                    )
                    for row in cursor.fetchall():
                        if row[0]:
                            existing_map[row[0]] = row[1]
                except Exception as e:
                    logger.warning(
                        "Could not query existing documents from Postgres: %s",
                        e,
                    )
    else:
        all_node_ids = list(index.docstore.docs.keys())
        for node in index.docstore.get_nodes(all_node_ids):
            doc_id = node.metadata.get("document_id")
            if doc_id:
                existing_map[doc_id] = node.metadata.get("modified")

    return existing_map


def update_llm_index(*, progress_bar_disable=False, rebuild=False) -> str:
    """
    Rebuild or update the LLM index.
    """
    VectorStoreFactory.setup_vector_store()

    documents = Document.objects.select_related(
        "correspondent",
        "document_type",
        "storage_path",
    ).prefetch_related(
        "tags",
        "notes",
        "custom_fields",
        "custom_fields__field",
    )
    if not documents.exists():
        return "No documents found to index."

    if rebuild or not vector_store_file_exists():
        if rebuild:
            (settings.LLM_INDEX_DIR / "meta.json").unlink(missing_ok=True)

        logger.info("Rebuilding LLM index.")
        embed_model = get_embedding_model()
        llama_settings.Settings.embed_model = embed_model
        storage_context = get_or_create_storage_context(rebuild=rebuild)

        if VectorStoreFactory.get_vector_store_backend() == "faiss":
            nodes = []
            for document in tqdm(documents, disable=progress_bar_disable):
                nodes.extend(build_document_node(document))

            index = VectorStoreIndex(
                nodes=nodes,
                storage_context=storage_context,
                embed_model=embed_model,
                show_progress=not progress_bar_disable,
            )
        else:
            # Postgres / Vector Store
            index = VectorStoreIndex.from_vector_store(
                vector_store=storage_context.vector_store,
                embed_model=embed_model,
            )
            # If rebuilding Postgres, we should ideally truncate but at least
            # we can batch insert.
            nodes = []
            for document in tqdm(documents, disable=progress_bar_disable):
                nodes.extend(build_document_node(document))

            if nodes:
                index.insert_nodes(nodes)

        msg = "LLM index rebuilt successfully."
    else:
        index = load_or_build_index()
        existing_doc_map = get_existing_docs_map(index)
        nodes = []

        for document in tqdm(documents, disable=progress_bar_disable):
            doc_id = str(document.pk)
            document_modified = document.modified.isoformat()

            if doc_id in existing_doc_map:
                if existing_doc_map[doc_id] == document_modified:
                    continue
                remove_document_from_index(document, index)

            nodes.extend(build_document_node(document))

        if nodes:
            index.insert_nodes(nodes)
            msg = f"LLM index updated with {len(nodes)} nodes."
        else:
            msg = "No changes detected in LLM index."

    if VectorStoreFactory.get_vector_store_backend() == "faiss":
        index.storage_context.persist(persist_dir=str(settings.LLM_INDEX_DIR))
    return msg


def llm_index_add_or_update_document(document: Document):
    new_nodes = build_document_node(document)
    index = load_or_build_index(nodes=new_nodes)
    remove_document_from_index(document, index)
    index.insert_nodes(new_nodes)
    if VectorStoreFactory.get_vector_store_backend() == "faiss":
        index.storage_context.persist(persist_dir=str(settings.LLM_INDEX_DIR))


def llm_index_remove_document(document: Document):
    index = load_or_build_index()
    remove_document_from_index(document, index)
    if VectorStoreFactory.get_vector_store_backend() == "faiss":
        index.storage_context.persist(persist_dir=str(settings.LLM_INDEX_DIR))


def truncate_content(content: str) -> str:
    from llama_index.core.indices.prompt_helper import PromptHelper
    from llama_index.core.prompts import PromptTemplate

    prompt_helper = PromptHelper(
        context_window=8192,
        num_output=512,
        chunk_overlap_ratio=0.1,
        chunk_size_limit=None,
    )
    splitter = TokenTextSplitter(separator=" ", chunk_size=512, chunk_overlap=50)
    content_chunks = splitter.split_text(content)
    truncated_chunks = prompt_helper.truncate(
        prompt=PromptTemplate(template="{content}"),
        text_chunks=content_chunks,
        padding=5,
    )
    return " ".join(truncated_chunks)


def query_similar_documents(
    document: Document,
    top_k: int = 5,
    document_ids: list[int] | None = None,
) -> list[Document]:
    if not vector_store_file_exists():
        return []

    index = load_or_build_index()
    filters = None
    if document_ids:
        filters = MetadataFilters(
            filters=[
                MetadataFilter(key="document_id", value=str(doc_id))
                for doc_id in document_ids
            ],
            condition=FilterCondition.OR,
        )

    from llama_index.core.retrievers import VectorIndexRetriever

    retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=top_k,
        filters=filters,
    )
    query_text = truncate_content(
        str(document.title or "") + "\n" + str(document.content or ""),
    )
    results = retriever.retrieve(query_text)

    top_document_ids = [
        int(node.metadata["document_id"])
        for node in results
        if "document_id" in node.metadata
    ]
    return list(Document.objects.filter(pk__in=top_document_ids))
