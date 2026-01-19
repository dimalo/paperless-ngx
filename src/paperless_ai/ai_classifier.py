import logging

from django.contrib.auth.models import User

from documents.models import Document
from documents.permissions import get_objects_for_user_owner_aware
from paperless.config import AIConfig
from paperless_ai.client import AIClient
from paperless_ai.indexing import query_similar_documents
from paperless_ai.indexing import truncate_content

logger = logging.getLogger("paperless_ai.rag_classifier")


def build_prompt_without_rag(document: Document) -> str:
    filename = document.filename or ""
    content = truncate_content(document.content[:4000] or "")

    return f"""
    You are a document classification assistant.

    Analyze the following document and extract the following information as a JSON object:
    - title: A short descriptive title
    - title_confidence: Confidence score (0.0-1.0) for the title
    - tags: Array of tags that reflect the content
    - tags_confidence: Object mapping tag indices to confidence scores (0.0-1.0)
    - correspondents: Array of names of people or organizations mentioned
    - correspondents_confidence: Object mapping correspondent indices to confidence scores (0.0-1.0)
    - document_types: Array of document type categories
    - document_types_confidence: Object mapping document type indices to confidence scores (0.0-1.0)
    - storage_paths: Array of suggested folder paths for storing the document
    - storage_paths_confidence: Object mapping storage path indices to confidence scores (0.0-1.0)
    - dates: Array of up to 3 relevant dates in YYYY-MM-DD format

    Provide confidence scores between 0.0 (no confidence) and 1.0 (full confidence) for each metadata item.

    Filename:
    {filename}

    Content:
    {content}
    """.strip()


def build_prompt_with_rag(document: Document, user: User | None = None) -> str:
    base_prompt = build_prompt_without_rag(document)
    context = truncate_content(get_context_for_document(document, user))

    return f"""{base_prompt}

    Additional context from similar documents:
    {context}
    """.strip()


def get_context_for_document(
    doc: Document,
    user: User | None = None,
    max_docs: int = 5,
) -> str:
    visible_documents = (
        get_objects_for_user_owner_aware(
            user,
            "view_document",
            Document,
        )
        if user
        else None
    )
    similar_docs = query_similar_documents(
        document=doc,
        document_ids=[document.pk for document in visible_documents]
        if visible_documents
        else None,
    )[:max_docs]
    context_blocks = []
    for similar in similar_docs:
        text = similar.content[:1000] or ""
        title = similar.title or similar.filename or "Untitled"
        context_blocks.append(f"TITLE: {title}\n{text}")
    return "\n\n".join(context_blocks)


def parse_ai_response(raw: dict) -> dict:
    """
    Parse AI response and return metadata in the legacy format for backward compatibility.
    """
    return {
        "title": raw.get("title", ""),
        "tags": raw.get("tags", []),
        "correspondents": raw.get("correspondents", []),
        "document_types": raw.get("document_types", []),
        "storage_paths": raw.get("storage_paths", []),
        "dates": raw.get("dates", []),
    }


def parse_ai_response_with_confidence(raw: dict) -> dict:
    """
    Parse AI response and return metadata with confidence scores.

    Returns a dictionary containing metadata fields with their confidence scores.
    Each field has a 'value' and 'confidence' key for title, or lists of dicts for arrays.
    """
    return {
        "title": {
            "value": raw.get("title", ""),
            "confidence": raw.get("title_confidence", 0.0),
        },
        "tags": [
            {"value": tag, "confidence": raw.get("tags_confidence", {}).get(i, 0.0)}
            for i, tag in enumerate(raw.get("tags", []))
        ],
        "correspondents": [
            {
                "value": corr,
                "confidence": raw.get("correspondents_confidence", {}).get(i, 0.0),
            }
            for i, corr in enumerate(raw.get("correspondents", []))
        ],
        "document_types": [
            {
                "value": dt,
                "confidence": raw.get("document_types_confidence", {}).get(i, 0.0),
            }
            for i, dt in enumerate(raw.get("document_types", []))
        ],
        "storage_paths": [
            {
                "value": sp,
                "confidence": raw.get("storage_paths_confidence", {}).get(i, 0.0),
            }
            for i, sp in enumerate(raw.get("storage_paths", []))
        ],
        "dates": raw.get("dates", []),
    }


def get_ai_document_classification(
    document: Document,
    user: User | None = None,
) -> dict:
    ai_config = AIConfig()

    prompt = (
        build_prompt_with_rag(document, user)
        if ai_config.llm_embedding_backend
        else build_prompt_without_rag(document)
    )

    client = AIClient()
    result = client.run_llm_query(prompt)
    return parse_ai_response(result)


def get_ai_document_classification_with_confidence(
    document: Document,
    user: User | None = None,
) -> dict:
    """
    Get AI document classification with confidence scores for auto-enhancement.
    """
    ai_config = AIConfig()

    prompt = (
        build_prompt_with_rag(document, user)
        if ai_config.llm_embedding_backend
        else build_prompt_without_rag(document)
    )

    client = AIClient()
    result = client.run_llm_query(prompt)
    return parse_ai_response_with_confidence(result)
