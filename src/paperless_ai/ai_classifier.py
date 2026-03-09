import logging

from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils.translation import get_language

from documents.models import Correspondent
from documents.models import Document
from documents.models import DocumentType
from documents.models import Tag
from documents.permissions import get_objects_for_user_owner_aware
from paperless.config import AIConfig
from paperless_ai.client import AIClient
from paperless_ai.indexing import query_similar_documents
from paperless_ai.indexing import truncate_content

logger = logging.getLogger("paperless_ai.rag_classifier")

AI_MAX_CONTENT_CHARS = 10000

CACHE_KEY_TAGS = "ai_classifier:available_tags"
CACHE_KEY_DOC_TYPES = "ai_classifier:available_document_types"
CACHE_KEY_CORRESPONDENTS = "ai_classifier:available_correspondents"
CACHE_TIMEOUT = 300  # 5 minutes
EMPTY_MESSAGE = "No values, yet, please suggest"


def get_available_tags(user: User | None = None) -> str:
    """Fetch available tags for the given user with caching."""
    cache_key = f"{CACHE_KEY_TAGS}:{user.id if user else 'global'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if user is not None:
        tags = get_objects_for_user_owner_aware(user, "view_tag", Tag).values_list(
            "name",
            flat=True,
        )
    else:
        tags = Tag.objects.values_list("name", flat=True)

    result = ", ".join(sorted(tags)) if tags else EMPTY_MESSAGE
    cache.set(cache_key, result, CACHE_TIMEOUT)
    return result


def get_available_document_types(user: User | None = None) -> str:
    """Fetch available document types for the given user with caching."""
    cache_key = f"{CACHE_KEY_DOC_TYPES}:{user.id if user else 'global'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if user is not None:
        doc_types = get_objects_for_user_owner_aware(
            user,
            "view_documenttype",
            DocumentType,
        ).values_list("name", flat=True)
    else:
        doc_types = DocumentType.objects.values_list("name", flat=True)

    result = ", ".join(sorted(doc_types)) if doc_types else EMPTY_MESSAGE
    cache.set(cache_key, result, CACHE_TIMEOUT)
    return result


def get_available_correspondents(user: User | None = None) -> str:
    """Fetch available correspondents for the given user with caching."""
    cache_key = f"{CACHE_KEY_CORRESPONDENTS}:{user.id if user else 'global'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if user is not None:
        correspondents = get_objects_for_user_owner_aware(
            user,
            "view_correspondent",
            Correspondent,
        ).values_list("name", flat=True)
    else:
        correspondents = Correspondent.objects.values_list("name", flat=True)

    result = ", ".join(sorted(correspondents)) if correspondents else EMPTY_MESSAGE
    cache.set(cache_key, result, CACHE_TIMEOUT)
    return result


DEFAULT_SYSTEM_PROMPT = """
You are a professional document classifier. Your task is to extract metadata from the document below.

Available Values:
- Tags: {available_tags}
- Document Types: {available_document_types}
- Correspondents: {available_correspondents}

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

DEFAULT_SYSTEM_PROMPT_DE = """
Du bist ein professioneller Dokumenten-Klassifizierer. Define Aufgabe ist es, Metadaten aus dem unten stehenden Document zu extrahieren.

Verfügbare Werte:
- Tags: {available_tags}
- Dokumenttypen: {available_document_types}
- Korrespondenten: {available_correspondents}

Gib ein einzelnes, streng gültiges JSON-Objekt mit diesen Feldern aus:
- title: (string) Ein prägnanter, beschreibender Title.
- title_confidence: (float 0.0-1.0)
- tags: (list of strings) Schlüsselwörter oder Kategorien.
- tags_confidence: (object) Zuordnung jedes Tags zu seinem Konfidenzwert (0.0-1.0).
- correspondents: (list of strings) Personen oder Organisationen.
- correspondents_confidence: (object) Zuordnung jedes Korrespondenten zu seinem Konfidenzwert (0.0-1.0).
- document_types: (list of strings) z.B. "Rechnung", "Brief".
- document_types_confidence: (object) Zuordnung jedes Typs zu seinem Konfidenzwert (0.0-1.0).
- storage_paths: (list of strings) Vorgeschlagene Ordnerpfade.
- storage_paths_confidence: (object) Zuordnung jedes Pfads zu seinem Konfidenzwert (0.0-1.0).
- dates: (list of strings) Bis zu 3 im Document gefundene Daten im Format YYYY-MM-DD.

Dokumenten-Dateiname: {filename}
Dokumenten-Inhalt:
{content}

Antworte NUR mit dem JSON-Objekt.
""".strip()


def build_prompt_without_rag(document: Document, user: User | None = None) -> str:
    ai_config = AIConfig()
    filename = document.filename or ""
    content = truncate_content(document.content[:AI_MAX_CONTENT_CHARS] or "")

    if ai_config.ai_system_prompt:
        system_prompt = ai_config.ai_system_prompt
    else:
        lang = get_language()
        if lang and lang.startswith("de"):
            system_prompt = DEFAULT_SYSTEM_PROMPT_DE
        else:
            system_prompt = DEFAULT_SYSTEM_PROMPT

    return system_prompt.format(
        filename=filename,
        content=content,
        available_tags=get_available_tags(user),
        available_document_types=get_available_document_types(user),
        available_correspondents=get_available_correspondents(user),
    )


def build_prompt_with_rag(document: Document, user: User | None = None) -> str:
    base_prompt = build_prompt_without_rag(document, user)
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
        document_ids=list(visible_documents.values_list("pk", flat=True))
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
        else build_prompt_without_rag(document, user)
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
        else build_prompt_without_rag(document, user)
    )

    client = AIClient()
    result = client.run_llm_query(prompt)
    return parse_ai_response_with_confidence(result)
