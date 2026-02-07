import logging
import re
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Tag

logger = logging.getLogger("paperless.docling")


def _coerce_value(value, data_type):
    """
    Attempts to coerce the Docling extracted value to the Paperless field type.
    """
    if value is None:
        return None

    if data_type == CustomField.FieldDataType.INT:
        return int(float(value))
    if data_type == CustomField.FieldDataType.FLOAT:
        return float(value)
    if data_type == CustomField.FieldDataType.DATE:
        if isinstance(value, datetime):
            return value.date()
        # Docling usually returns strings for now
        return datetime.fromisoformat(str(value)).date()
    if data_type == CustomField.FieldDataType.BOOL:
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "y")
    if data_type == CustomField.FieldDataType.MONETARY:
        # Paperless expects either a 3-char ISO code prefix + amount
        # or just a numeric amount. Docling often returns "$12.34".
        # We try to normalize this to a numeric string.
        s = str(value).strip()
        # Remove common currency symbols
        s = re.sub(r"[$€£¥]", "", s)
        # Remove spaces
        s = s.replace(" ", "")
        return s

    return str(value)


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
        # 1. Apply Semantic Tags
        # We look for tags named "Docling: <LABEL>"
        labels = metadata.get("docling_labels", [])
        if labels:
            applied_tags = []
            for label in labels:
                tag_name = f"Docling: {label.title()}"
                try:
                    tag = Tag.objects.get(name=tag_name)
                    applied_tags.append(tag)
                except Tag.DoesNotExist:
                    continue

            if applied_tags:
                document.tags.add(*applied_tags)
                logger.info(f"Applied semantic tags: {[t.name for t in applied_tags]}")

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
                "date": "document date",
                "total": "amount",
            }

            applied_fields = []
            unmapped_keys = []
            failed_fields = []

            for key, value in kv_pairs.items():
                target_name = key.lower().strip()
                # Check synonym map
                mapped_name = synonyms.get(target_name, target_name)

                logger.debug(
                    f"Attempting to map Docling key '{key}' (normalized: '{target_name}', mapped: '{mapped_name}')",
                )

                field = all_fields.get(mapped_name)
                if field:
                    try:
                        coerced_value = _coerce_value(value, field.data_type)
                        logger.debug(
                            f"Matched field '{field.name}', coerced value: '{coerced_value}'",
                        )

                        # Get the correct value field name (e.g. value_text, value_int)
                        value_field = CustomFieldInstance.get_value_field_name(
                            field.data_type,
                        )

                        # Create or update instance
                        instance, created = CustomFieldInstance.objects.get_or_create(
                            document=document,
                            field=field,
                            defaults={value_field: coerced_value},
                        )
                        if not created:
                            setattr(instance, value_field, coerced_value)
                            instance.save()
                        applied_fields.append(field.name)
                    except (ValueError, TypeError, ValidationError, Exception) as e:
                        logger.warning(
                            f"Failed to apply Docling value '{value}' to field "
                            f"'{field.name}' ({field.data_type}): {e}",
                        )
                        failed_fields.append(field.name)
                else:
                    unmapped_keys.append(key)

            if applied_fields:
                logger.info(f"Populated custom fields from Docling: {applied_fields}")
            if failed_fields:
                logger.warning(
                    f"Failed to populate these custom fields: {failed_fields}",
                )
            if unmapped_keys:
                logger.info(f"Docling found unmapped metadata keys: {unmapped_keys}")
