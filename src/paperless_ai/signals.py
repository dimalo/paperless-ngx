import logging

from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.db.models.signals import pre_save
from django.dispatch import receiver

from documents.models import Document
from documents.tasks import llmindex_index
from paperless.config import AIConfig
from paperless.models import ApplicationConfiguration
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


@receiver(pre_save, sender=ApplicationConfiguration)
def handle_app_config_pre_save(sender, instance, **kwargs):
    """
    Captures the current state of the application configuration before saving.
    """
    if instance.pk:
        try:
            instance._old_instance = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            instance._old_instance = None
    else:
        instance._old_instance = None


@receiver(post_save, sender=ApplicationConfiguration)
def handle_app_config_save(sender, instance, created, **kwargs):
    """
    Triggers an index rebuild if the vector store settings have changed.
    """
    if created:
        # If it's a new instance, we should probably index if AI is enabled.
        if instance.ai_enabled:
            logger.info("New application settings created with AI enabled, indexing...")
            llmindex_index.delay(rebuild=True, scheduled=False)
        return

    # Fields that should trigger a rebuild if changed
    REBUILD_TRIGGER_FIELDS = [
        "ai_enabled",
        "llm_embedding_backend",
        "llm_embedding_model",
        "llm_embedding_endpoint",
        "llm_embedding_api_key",
        "vector_store_backend",
        "vector_store_host",
        "vector_store_port",
        "vector_store_user",
        "vector_store_password",
        "vector_store_database",
    ]

    old_instance = getattr(instance, "_old_instance", None)

    if not old_instance:
        # Should not happen for an update, but as a fallback trigger it
        logger.info("Application settings updated, triggering index update (fallback).")
        llmindex_index.delay(rebuild=True, scheduled=False)
        return

    changed_fields = []
    for field in REBUILD_TRIGGER_FIELDS:
        old_val = getattr(old_instance, field)
        new_val = getattr(instance, field)
        if old_val != new_val:
            changed_fields.append(field)

    if changed_fields:
        logger.info(
            f"AI/Vector store settings changed ({', '.join(changed_fields)}), "
            "triggering index rebuild...",
        )
        llmindex_index.delay(rebuild=True, scheduled=False)
    else:
        logger.debug("No AI/Vector store settings changed, skipping index rebuild.")
