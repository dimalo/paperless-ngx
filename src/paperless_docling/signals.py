def get_parser(*args, **kwargs):
    from paperless_docling.parsers import DoclingDocumentParser

    return DoclingDocumentParser(*args, **kwargs)


def docling_consumer_declaration(sender, **kwargs):
    from django.conf import settings

    from paperless.models import ApplicationConfiguration

    # Check DB setting first, then env var
    config = ApplicationConfiguration.objects.first()
    ocr_engine = (
        config.ocr_engine if config and config.ocr_engine else settings.OCR_ENGINE
    )

    if not ocr_engine.startswith("docling"):
        return None

    return {
        "parser": get_parser,
        "weight": 3,
        "mime_types": ["application/pdf", "image/*"],
    }
