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
    You are a professional document classifier. Your task is to extract metadata from the document below.

    Output a single, strictly valid JSON object with these fields:
    - title: (string) A concise, descriptive title.
    - title_confidence: (float 0.0-1.0)
    - tags: (list of strings) Keywords or categories.
    - tags_confidence: (object) Mapping each tag to its 0.0-1.0 confidence score.
    - correspondents: (list of strings) People or organizations.
    - correspondents_confidence: (object) Mapping each correspondent to its 0.0-1.0 confidence score.
    - document_types: (list of strings) e.g. "Invoice", "Letter".
    - document_types_confidence: (object) Mapping each type to its 0.0-1.0 confidence score.
    - storage_paths: (list of strings) Suggested folder paths.
    - storage_paths_confidence: (object) Mapping each path to its 0.0-1.0 confidence score.
    - dates: (list of strings) Up to 3 dates found in YYYY-MM-DD format.

    Document Filename: {filename}
    Document Content:
    {content}

    Respond ONLY with the JSON object.
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
    Handles confidence lookup by index (int or string) or by the name/value itself.
    """

    def get_conf(field_name, index, value):
        conf_dict = raw.get(f"{field_name}_confidence", {})
        # Try by index (int)
        if index in conf_dict:
            return conf_dict[index]
        # Try by index (str)
        if str(index) in conf_dict:
            return conf_dict[str(index)]
        # Try by value (name)
        if str(value) in conf_dict:
            return conf_dict[str(value)]
        return 0.0

    return {
        "title": {
            "value": raw.get("title", ""),
            "confidence": raw.get("title_confidence", 0.0),
        },
        "tags": [
            {"value": tag, "confidence": get_conf("tags", i, tag)}
            for i, tag in enumerate(raw.get("tags", []))
        ],
        "correspondents": [
            {"value": corr, "confidence": get_conf("correspondents", i, corr)}
            for i, corr in enumerate(raw.get("correspondents", []))
        ],
        "document_types": [
            {"value": dt, "confidence": get_conf("document_types", i, dt)}
            for i, dt in enumerate(raw.get("document_types", []))
        ],
        "storage_paths": [
            {"value": sp, "confidence": get_conf("storage_paths", i, sp)}
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
