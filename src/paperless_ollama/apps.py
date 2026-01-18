from django.apps import AppConfig

from paperless_ollama.signals import ollama_consumer_declaration


class PaperlessOllamaConfig(AppConfig):
    name = "paperless_ollama"

    def ready(self):
        from documents.signals import document_consumer_declaration

        document_consumer_declaration.connect(ollama_consumer_declaration)

        AppConfig.ready(self)
