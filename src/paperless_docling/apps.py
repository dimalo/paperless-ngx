from django.apps import AppConfig

from paperless_docling.signals import docling_consumer_declaration


class PaperlessDoclingConfig(AppConfig):
    name = "paperless_docling"

    def ready(self):
        from documents.signals import document_consumer_declaration

        document_consumer_declaration.connect(docling_consumer_declaration)

        AppConfig.ready(self)
