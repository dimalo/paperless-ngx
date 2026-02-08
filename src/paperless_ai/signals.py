import logging

from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver

from documents.models import Document
from paperless.config import AIConfig
from paperless_ai.indexing import llm_index_add_or_update_document
from paperless_ai.indexing import llm_index_remove_document

logger = logging.getLogger("paperless_ai.signals")


@receiver(post_save, sender=Document)
def document_updated(sender, instance, created, **kwargs):
    config = AIConfig()
    if not config.llm_index_enabled:
        return

    try:
        llm_index_add_or_update_document(instance)
    except Exception as e:
        logger.warning(f"Failed to update LLM index for document {instance.pk}: {e}")


@receiver(post_delete, sender=Document)
def document_deleted(sender, instance, **kwargs):
    config = AIConfig()
    if not config.llm_index_enabled:
        return

    try:
        llm_index_remove_document(instance)
    except Exception as e:
        logger.warning(f"Failed to remove document {instance.pk} from LLM index: {e}")
