def get_parser(*args, **kwargs):
    from paperless_docling.parsers import DoclingDocumentParser

    return DoclingDocumentParser(*args, **kwargs)


def docling_consumer_declaration(sender, **kwargs):
    return {
        "parser": get_parser,
        "weight": 3,
        "mime_types": ["application/pdf", "image/*"],
    }
