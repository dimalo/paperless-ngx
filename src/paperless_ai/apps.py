from django.apps import AppConfig


class PaperlessAIConfig(AppConfig):
    name = "paperless_ai"
    verbose_name = "Paperless AI"

    def ready(self):
        import paperless_ai.signals  # noqa: F401
