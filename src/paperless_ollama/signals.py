def get_parser(*args, **kwargs):
    from paperless_ollama.parsers import OllamaDocumentParser

    return OllamaDocumentParser(*args, **kwargs)


def ollama_consumer_declaration(sender, **kwargs):
    from django.conf import settings

    # Check DB setting first, then env var
    from django.db.utils import ProgrammingError

    from paperless.models import ApplicationConfiguration

    try:
        config = ApplicationConfiguration.objects.first()
        ocr_engine = (
            config.ocr_engine if config and config.ocr_engine else settings.OCR_ENGINE
        )
    except ProgrammingError:
        ocr_engine = settings.OCR_ENGINE

    if ocr_engine != "ollama":
        return None

    return {
        "parser": get_parser,
        "weight": 4,
        "mime_types": {
            "application/pdf": ".pdf",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/tiff": ".tif",
            "image/bmp": ".bmp",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/heic": ".heic",
            "text/plain": ".txt",
            "text/markdown": ".md",
        },
    }
