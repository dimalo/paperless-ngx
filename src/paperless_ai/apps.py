from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PaperlessAIConfig(AppConfig):
    name = "paperless_ai"
    verbose_name = _("Paperless AI")

    def ready(self) -> None:
        import paperless_ai.signals  # noqa: F401
