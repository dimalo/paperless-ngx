import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import override_settings

from documents.models import Document
from paperless_ai.ai_classifier import build_prompt_with_rag
from paperless_ai.ai_classifier import build_prompt_without_rag
from paperless_ai.ai_classifier import get_ai_document_classification
from paperless_ai.ai_classifier import get_context_for_document


@pytest.fixture(autouse=True)
def mock_celery_delay():
    with patch("documents.tasks.llmindex_index.delay") as mock_delay:
        yield mock_delay


@pytest.fixture
def mock_document():
    doc = MagicMock(spec=Document)
    doc.title = "Test Title"
    doc.filename = "test_file.pdf"
    doc.created = "2023-01-01"
    doc.added = "2023-01-02"
    doc.modified = "2023-01-03"

    tag1 = MagicMock()
    tag1.name = "Tag1"
    tag2 = MagicMock()
    tag2.name = "Tag2"
    doc.tags.all = MagicMock(return_value=[tag1, tag2])

    doc.document_type = MagicMock()
    doc.document_type.name = "Invoice"
    doc.correspondent = MagicMock()
    doc.correspondent.name = "Test Correspondent"
    doc.archive_serial_number = "12345"
    doc.content = "This is the document content."

    cf1 = MagicMock(__str__=lambda x: "Value1")
    cf1.field = MagicMock()
    cf1.field.name = "Field1"
    cf1.value = "Value1"
    cf2 = MagicMock(__str__=lambda x: "Value2")
    cf2.field = MagicMock()
    cf2.field.name = "Field2"
    cf2.value = "Value2"
    doc.custom_fields.all = MagicMock(return_value=[cf1, cf2])

    return doc


@pytest.fixture
def mock_similar_documents():
    doc1 = MagicMock()
    doc1.content = "Content of document 1"
    doc1.title = "Title 1"
    doc1.filename = "file1.txt"

    doc2 = MagicMock()
    doc2.content = "Content of document 2"
    doc2.title = None
    doc2.filename = "file2.txt"

    doc3 = MagicMock()
    doc3.content = None
    doc3.title = None
    doc3.filename = None

    return [doc1, doc2, doc3]


@pytest.mark.django_db
@override_settings(
    LLM_BACKEND="ollama",
    LLM_MODEL="some_model",
)
def test_get_ai_document_classification_success(mock_document):
    with patch("litellm.completion") as mock_completion:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "title": "Test Title",
                "tags": ["test", "document"],
                "correspondents": ["John Doe"],
                "document_types": ["report"],
                "storage_paths": ["Reports"],
                "dates": ["2023-01-01"],
            },
        )
        mock_completion.return_value = mock_response

        result = get_ai_document_classification(mock_document)

        assert result["title"] == "Test Title"
        assert result["tags"] == ["test", "document"]
        assert result["correspondents"] == ["John Doe"]
        assert result["document_types"] == ["report"]
        assert result["storage_paths"] == ["Reports"]
        assert result["dates"] == ["2023-01-01"]


@pytest.mark.django_db
@patch("litellm.completion")
def test_get_ai_document_classification_failure(mock_completion, mock_document):
    mock_completion.side_effect = Exception("LLM query failed")

    # assert raises an exception
    with pytest.raises(Exception):
        get_ai_document_classification(mock_document)


@pytest.mark.django_db
@patch("litellm.completion")
@patch("paperless_ai.ai_classifier.build_prompt_with_rag")
@override_settings(
    LLM_EMBEDDING_BACKEND="huggingface",
    LLM_EMBEDDING_MODEL="some_model",
    LLM_BACKEND="ollama",
    LLM_MODEL="some_model",
)
def test_use_rag_if_configured(
    mock_build_prompt_with_rag,
    mock_completion,
    mock_document,
):
    mock_build_prompt_with_rag.return_value = "Prompt with RAG"
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "title": "Test",
            "tags": [],
            "correspondents": [],
            "document_types": [],
            "storage_paths": [],
            "dates": [],
        },
    )
    mock_completion.return_value = mock_response
    get_ai_document_classification(mock_document)
    mock_build_prompt_with_rag.assert_called_once()


@pytest.mark.django_db
@patch("litellm.completion")
@patch("paperless_ai.ai_classifier.build_prompt_without_rag")
@patch("paperless_ai.ai_classifier.AIConfig")
@override_settings(
    LLM_BACKEND="ollama",
    LLM_MODEL="some_model",
)
def test_use_without_rag_if_not_configured(
    mock_ai_config,
    mock_build_prompt_without_rag,
    mock_completion,
    mock_document,
):
    mock_ai_config.return_value.llm_embedding_backend = None
    mock_build_prompt_without_rag.return_value = "Prompt without RAG"
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        {
            "title": "Test",
            "tags": [],
            "correspondents": [],
            "document_types": [],
            "storage_paths": [],
            "dates": [],
        },
    )
    mock_completion.return_value = mock_response
    get_ai_document_classification(mock_document)
    mock_build_prompt_without_rag.assert_called_once()


@pytest.mark.django_db
@override_settings(
    LLM_EMBEDDING_BACKEND="huggingface",
    LLM_BACKEND="ollama",
    LLM_MODEL="some_model",
)
def test_prompt_with_without_rag(mock_document):
    with patch(
        "paperless_ai.ai_classifier.get_context_for_document",
        return_value="Context from similar documents",
    ):
        prompt = build_prompt_without_rag(mock_document)
        assert "Additional context from similar documents:" not in prompt

        prompt = build_prompt_with_rag(mock_document)
        assert "Additional context from similar documents:" in prompt


@patch("paperless_ai.ai_classifier.query_similar_documents")
def test_get_context_for_document(
    mock_query_similar_documents,
    mock_document,
    mock_similar_documents,
):
    mock_query_similar_documents.return_value = mock_similar_documents

    result = get_context_for_document(mock_document, max_docs=2)

    expected_result = (
        "TITLE: Title 1\nContent of document 1\n\n"
        "TITLE: file2.txt\nContent of document 2"
    )
    assert result == expected_result
    mock_query_similar_documents.assert_called_once()


def test_get_context_for_document_no_similar_docs(mock_document):
    with patch("paperless_ai.ai_classifier.query_similar_documents", return_value=[]):
        result = get_context_for_document(mock_document)
        assert result == ""


# Tests for cached helper functions and dynamic placeholders

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings

from documents.models import Correspondent
from documents.models import DocumentType
from documents.models import Tag
from paperless_ai.ai_classifier import CACHE_KEY_CORRESPONDENTS
from paperless_ai.ai_classifier import CACHE_KEY_DOC_TYPES
from paperless_ai.ai_classifier import CACHE_KEY_TAGS
from paperless_ai.ai_classifier import EMPTY_MESSAGE
from paperless_ai.ai_classifier import get_available_correspondents
from paperless_ai.ai_classifier import get_available_document_types
from paperless_ai.ai_classifier import get_available_tags


@pytest.mark.django_db
def test_get_available_tags_cache_miss():
    """Test that tags are fetched from DB and cached on cache miss."""
    cache.clear()
    Tag.objects.create(name="Important")
    Tag.objects.create(name="Work")

    result = get_available_tags()

    assert "Important" in result
    assert "Work" in result
    assert cache.get(f"{CACHE_KEY_TAGS}:global") == result


@pytest.mark.django_db
def test_get_available_tags_cache_hit():
    """Test that cached tags are returned without DB query on cache hit."""
    cache.set(f"{CACHE_KEY_TAGS}:global", "CachedTag1, CachedTag2")

    with patch.object(Tag.objects, "values_list") as mock_values:
        result = get_available_tags()
        mock_values.assert_not_called()

    assert result == "CachedTag1, CachedTag2"


@pytest.mark.django_db
def test_get_available_tags_empty():
    """Test empty state message when no tags exist."""
    cache.clear()
    Tag.objects.all().delete()

    result = get_available_tags()

    assert result == EMPTY_MESSAGE


@pytest.mark.django_db
def test_get_available_document_types_cache_miss():
    """Test that document types are fetched from DB and cached on cache miss."""
    cache.clear()
    DocumentType.objects.create(name="Invoice")
    DocumentType.objects.create(name="Receipt")

    result = get_available_document_types()

    assert "Invoice" in result
    assert "Receipt" in result
    assert cache.get(f"{CACHE_KEY_DOC_TYPES}:global") == result


@pytest.mark.django_db
def test_get_available_document_types_cache_hit():
    """Test that cached document types are returned without DB query on cache hit."""
    cache.set(f"{CACHE_KEY_DOC_TYPES}:global", "CachedType1, CachedType2")

    with patch.object(DocumentType.objects, "values_list") as mock_values:
        result = get_available_document_types()
        mock_values.assert_not_called()

    assert result == "CachedType1, CachedType2"


@pytest.mark.django_db
def test_get_available_document_types_empty():
    """Test empty state message when no document types exist."""
    cache.clear()
    DocumentType.objects.all().delete()

    result = get_available_document_types()

    assert result == EMPTY_MESSAGE


@pytest.mark.django_db
def test_get_available_correspondents_cache_miss():
    """Test that correspondents are fetched from DB and cached on cache miss."""
    cache.clear()
    Correspondent.objects.create(name="Alice")
    Correspondent.objects.create(name="Bob")

    result = get_available_correspondents()

    assert "Alice" in result
    assert "Bob" in result
    assert cache.get(f"{CACHE_KEY_CORRESPONDENTS}:global") == result


@pytest.mark.django_db
def test_get_available_correspondents_cache_hit():
    """Test that cached correspondents are returned without DB query on cache hit."""
    cache.set(f"{CACHE_KEY_CORRESPONDENTS}:global", "CachedCorr1, CachedCorr2")

    with patch.object(Correspondent.objects, "values_list") as mock_values:
        result = get_available_correspondents()
        mock_values.assert_not_called()

    assert result == "CachedCorr1, CachedCorr2"


@pytest.mark.django_db
def test_get_available_correspondents_empty():
    """Test empty state message when no correspondents exist."""
    cache.clear()
    Correspondent.objects.all().delete()

    result = get_available_correspondents()

    assert result == EMPTY_MESSAGE


@pytest.mark.django_db
def test_helper_functions_with_user_permissions():
    """Test that user permissions filter results."""

    cache.clear()
    user = User.objects.create_user(username="testuser")

    # Create objects
    tag1 = Tag.objects.create(name="Tag1")
    tag2 = Tag.objects.create(name="Tag2")
    doc_type = DocumentType.objects.create(name="Invoice")
    correspondent = Correspondent.objects.create(name="John")

    # Mock the permission function to return filtered results
    with patch(
        "paperless_ai.ai_classifier.get_objects_for_user_owner_aware",
    ) as mock_perm:
        mock_perm.return_value.values_list.return_value = ["Tag1"]

        result = get_available_tags(user)

        mock_perm.assert_called_once_with(user, "view_tag", Tag)
        assert result == "Tag1"
        assert cache.get(f"{CACHE_KEY_TAGS}:{user.id}") == "Tag1"


# Tests for prompt building with placeholders


@pytest.mark.django_db
@patch("paperless_ai.ai_classifier.get_available_tags")
@patch("paperless_ai.ai_classifier.get_available_document_types")
@patch("paperless_ai.ai_classifier.get_available_correspondents")
def test_build_prompt_without_rag_with_placeholders(
    mock_get_correspondents,
    mock_get_doc_types,
    mock_get_tags,
    mock_document,
):
    """Test that all placeholders are replaced in the prompt."""
    mock_get_tags.return_value = "Important, Work"
    mock_get_doc_types.return_value = "Invoice, Receipt"
    mock_get_correspondents.return_value = "Alice, Bob"

    prompt = build_prompt_without_rag(mock_document)

    assert "- Tags: Important, Work" in prompt
    assert "- Document Types: Invoice, Receipt" in prompt
    assert "- Correspondents: Alice, Bob" in prompt
    assert "Document Filename: test_file.pdf" in prompt
    assert "This is the document content." in prompt


@pytest.mark.django_db
@patch("paperless_ai.ai_classifier.AIConfig")
@patch("paperless_ai.ai_classifier.get_available_tags")
@patch("paperless_ai.ai_classifier.get_available_document_types")
@patch("paperless_ai.ai_classifier.get_available_correspondents")
def test_build_prompt_custom_prompt_with_placeholders(
    mock_get_correspondents,
    mock_get_doc_types,
    mock_get_tags,
    mock_ai_config,
    mock_document,
):
    """Test custom prompt with placeholders is correctly formatted."""
    mock_get_tags.return_value = "Tag1, Tag2"
    mock_get_doc_types.return_value = "Type1"
    mock_get_correspondents.return_value = "Corr1"

    custom_prompt = """
Custom prompt with {filename} and {content}.
Tags: {available_tags}
Types: {available_document_types}
Correspondents: {available_correspondents}
"""
    mock_ai_config.return_value.ai_system_prompt = custom_prompt

    prompt = build_prompt_without_rag(mock_document)

    assert "Custom prompt with test_file.pdf" in prompt
    assert "Tags: Tag1, Tag2" in prompt
    assert "Types: Type1" in prompt
    assert "Correspondents: Corr1" in prompt


@pytest.mark.django_db
def test_build_prompt_backward_compatibility(mock_document):
    """Test that old custom prompts without new placeholders still work."""
    with patch("paperless_ai.ai_classifier.AIConfig") as mock_ai_config:
        old_prompt = "Process {filename} with content: {content}"
        mock_ai_config.return_value.ai_system_prompt = old_prompt

        prompt = build_prompt_without_rag(mock_document)

        assert "test_file.pdf" in prompt
        assert "This is the document content." in prompt


@pytest.mark.django_db
@patch("paperless_ai.ai_classifier.get_available_tags")
@patch("paperless_ai.ai_classifier.get_available_document_types")
@patch("paperless_ai.ai_classifier.get_available_correspondents")
def test_build_prompt_respects_user_permissions(
    mock_get_correspondents,
    mock_get_doc_types,
    mock_get_tags,
    mock_document,
):
    """Test that user parameter is passed to helper functions."""
    user = MagicMock(spec=User)

    build_prompt_without_rag(mock_document, user)

    mock_get_tags.assert_called_once_with(user)
    mock_get_doc_types.assert_called_once_with(user)
    mock_get_correspondents.assert_called_once_with(user)
