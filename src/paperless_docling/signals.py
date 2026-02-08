def get_parser(*args, **kwargs):
    from paperless_docling.parsers import DoclingDocumentParser

    return DoclingDocumentParser(*args, **kwargs)


def docling_consumer_declaration(sender, **kwargs):
    from django.conf import settings

    # Check DB setting first, then env var
    from django.db.utils import OperationalError
    from django.db.utils import ProgrammingError

    from paperless.models import ApplicationConfiguration

    try:
        config = ApplicationConfiguration.objects.first()
        ocr_engine = (
            config.ocr_engine if config and config.ocr_engine else settings.OCR_ENGINE
        )
    except (ProgrammingError, OperationalError):
        ocr_engine = settings.OCR_ENGINE

    if not ocr_engine.startswith("docling"):
        return None

    return {
        "parser": get_parser,
        "weight": 3,
        "mime_types": ["application/pdf", "image/*"],
    }
