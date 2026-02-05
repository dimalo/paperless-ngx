from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PaperlessDoclingConfig(AppConfig):
    name = "paperless_docling"
    verbose_name = _("Paperless Docling")

    def ready(self):
        import paperless_docling.signals  # noqa: F401
