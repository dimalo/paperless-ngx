from django.dispatch import receiver

from documents.signals import document_consumer_declaration
from documents.signals import document_consumption_finished


@receiver(document_consumption_finished)
def apply_docling_metadata_on_finish(sender, document, logging_group, **kwargs):
    """
    Decoupled receiver that applies Docling metadata stored in cache
    during the parsing phase.
    """
    from django.core.cache import cache

    from paperless_docling.utils import apply_docling_metadata

    cache_key = f"docling_meta_{logging_group}"
    metadata = cache.get(cache_key)

    if metadata:
        try:
            apply_docling_metadata(document, metadata)
        finally:
            cache.delete(cache_key)


@receiver(document_consumer_declaration)
def docling_consumer_declaration(sender, **kwargs):

    # We register the parser if it's potentially available.
    # The OCR Broker (documents/parsers.py) will decide if it's
    # the preferred engine based on global priority or workflow settings.

    if not is_docling_available():
        return None

    return {
        "parser": get_parser,
        "weight": 0,
        "engine_id": "docling",
        "mime_types": {
            "application/pdf": ".pdf",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/tiff": ".tiff",
            "image/webp": ".webp",
        },
    }


def get_parser(logging_group, progress_callback=None):
    from paperless_docling.parsers import DoclingDocumentParser

    return DoclingDocumentParser(logging_group, progress_callback)


def is_docling_available():
    from django.conf import settings

    # Available if endpoint is set in settings
    if getattr(settings, "DOCLING_ENDPOINT", None):
        return True

    # Or if local library is installed
    try:
        import docling  # noqa: F401

        return True
    except ImportError:
        return False
