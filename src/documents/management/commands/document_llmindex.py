from django.core.management import BaseCommand
from django.db import transaction

from documents.management.commands.mixins import ProgressBarMixin
from documents.tasks import llmindex_index


class Command(ProgressBarMixin, BaseCommand):
    help = "Manages the LLM-based vector index for Paperless."

    def add_arguments(self, parser):
        parser.add_argument("command", choices=["rebuild", "update", "setup"])
        self.add_argument_progress_bar_mixin(parser)

    def handle(self, *args, **options):
        self.handle_progress_bar_mixin(**options)
        command = options["command"]

        from paperless_ai.vector_store import VectorStoreFactory

        setup_success = VectorStoreFactory.setup_vector_store()

        if command == "setup":
            if setup_success:
                self.stdout.write(self.style.SUCCESS("Vector store setup completed."))  # type: ignore
            else:
                self.stdout.write(self.style.ERROR("Vector store setup failed."))  # type: ignore
            return

        with transaction.atomic():  # type: ignore
            llmindex_index(
                progress_bar_disable=self.no_progress_bar,
                rebuild=command == "rebuild",
                scheduled=False,
            )
