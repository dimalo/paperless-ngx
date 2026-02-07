import logging

from django.db import transaction
from django.dispatch import receiver

from documents.signals import document_consumer_declaration
from documents.signals import document_consumption_finished

logger = logging.getLogger("paperless.docling")


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

    logger.debug(
        f"Signal received for {document} (group: {logging_group}), "
        f"metadata in cache: {metadata is not None}",
    )

    if metadata:

        def _apply():
            try:
                apply_docling_metadata(document, metadata)
            finally:
                cache.delete(cache_key)

        transaction.on_commit(_apply)


@receiver(document_consumer_declaration)
def docling_local_consumer_declaration(sender, **kwargs):
    """
    Register Docling local parser if the library is installed.
    """
    if not is_docling_local_available():
        return None

    return {
        "parser": get_local_parser,
        "weight": 0,
        "engine_id": "docling_local",
        "mime_types": {
            "application/pdf": ".pdf",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/tiff": ".tiff",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
            "image/gif": ".gif",
        },
    }


@receiver(document_consumer_declaration)
def docling_remote_consumer_declaration(sender, **kwargs):
    """
    Register Docling remote parser if endpoint is configured.
    """
    if not is_docling_remote_available():
        return None

    return {
        "parser": get_remote_parser,
        "weight": 0,
        "engine_id": "docling_remote",
        "mime_types": {
            "application/pdf": ".pdf",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/tiff": ".tiff",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
            "image/gif": ".gif",
        },
    }


def get_local_parser(logging_group, progress_callback=None):
    from paperless_docling.parsers import DoclingDocumentParser

    return DoclingDocumentParser(logging_group, progress_callback, mode="local")


def get_remote_parser(logging_group, progress_callback=None):
    from paperless_docling.parsers import DoclingDocumentParser

    return DoclingDocumentParser(logging_group, progress_callback, mode="remote")


def is_docling_local_available():
    """Check if local Docling library is installed."""
    try:
        import docling  # noqa: F401

        return True
    except ImportError:
        return False


def is_docling_remote_available():
    """Check if Docling remote endpoint is configured."""
    from paperless_docling.parsers import DoclingDocumentParser

    # Initialize parser to get access to its settings (which handles DB + ENV)
    # We use a dummy logging group
    try:
        parser = DoclingDocumentParser("signal_check")
        return bool(parser.settings.endpoint)
    except Exception:
        # Fallback to pure settings if something fails
        from django.conf import settings

        return bool(getattr(settings, "DOCLING_ENDPOINT", None))
