import logging

from django.db import transaction

from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Tag

logger = logging.getLogger("paperless.docling")


def apply_docling_metadata(document, metadata: dict):
    """
    Applies extracted Docling metadata to a Document.

    metadata format:
    {
        "docling_key_value": {"Key": "Value", ...},
        "docling_labels": {"TABLE", "HANDWRITTEN", ...}
    }
    """
    if not metadata:
        return

    with transaction.atomic():
        # 1. Apply Semantic Tags (Only if they exist)
        # We look for tags named "Docling: <LABEL>"
        labels = metadata.get("docling_labels", set())
        if labels:
            existing_tags = Tag.objects.filter(
                name__in=[f"Docling: {label.title()}" for label in labels],
            )
            if existing_tags.exists():
                document.tags.add(*existing_tags)
                logger.info(f"Applied semantic tags: {[t.name for t in existing_tags]}")

        # 2. Map Key-Value pairs to Custom Fields
        # Strategy: Match existing Custom Field names (case-insensitive)
        kv_pairs = metadata.get("docling_key_value", {})
        if kv_pairs:
            # Fetch all custom fields once
            all_fields = {f.name.lower(): f for f in CustomField.objects.all()}

            # Common synonyms map
            synonyms = {
                "inv. no": "invoice number",
                "invoice no": "invoice number",
                "total amount": "total",
                "net amount": "net",
            }

            applied_fields = []
            unmapped_keys = []

            for key, value in kv_pairs.items():
                target_name = key.lower()
                # Check synonym map
                target_name = synonyms.get(target_name, target_name)

                field = all_fields.get(target_name)
                if field:
                    # Get the correct value field name (e.g. value_text, value_int)
                    value_field = CustomFieldInstance.get_value_field_name(
                        field.data_type,
                    )

                    # Create or update instance
                    instance, created = CustomFieldInstance.objects.get_or_create(
                        document=document,
                        field=field,
                        defaults={value_field: value},
                    )
                    if not created:
                        setattr(instance, value_field, value)
                        instance.save()
                    applied_fields.append(field.name)
                else:
                    unmapped_keys.append(key)

            if applied_fields:
                logger.info(f"Populated custom fields from Docling: {applied_fields}")
            if unmapped_keys:
                logger.info(f"Docling found unmapped metadata keys: {unmapped_keys}")
