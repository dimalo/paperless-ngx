from django.apps import apps


def ollama_consumer_declaration(sender, **kwargs):
    return {
        "parser": apps.get_app_config("paperless_ollama").parser_class,
        "weight": 4,
        "mime_types": {
            "application/pdf",
            "image/png",
            "image/jpeg",
            "image/tiff",
            "image/bmp",
            "image/gif",
            "image/webp",
            "image/heic",
        },
    }
