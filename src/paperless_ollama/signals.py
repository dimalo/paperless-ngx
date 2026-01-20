def get_parser(*args, **kwargs):
    from paperless_ollama.parsers import OllamaDocumentParser

    return OllamaDocumentParser(*args, **kwargs)


def ollama_consumer_declaration(sender, **kwargs):
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
        },
    }
