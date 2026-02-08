import difflib
import logging
import re

from django.contrib.auth.models import User

from documents.models import Correspondent
from documents.models import DocumentType
from documents.models import StoragePath
from documents.models import Tag
from documents.permissions import get_objects_for_user_owner_aware

MATCH_THRESHOLD = 0.8

logger = logging.getLogger("paperless_ai.matching")


def match_tags_by_name(names: list[str], user: User) -> list[Tag]:
    queryset = get_objects_for_user_owner_aware(
        user,
        ["view_tag"],
        Tag,
    )
    return _match_names_to_queryset(names, queryset, "name")


def match_correspondents_by_name(names: list[str], user: User) -> list[Correspondent]:
    queryset = get_objects_for_user_owner_aware(
        user,
        ["view_correspondent"],
        Correspondent,
    )
    return _match_names_to_queryset(names, queryset, "name")


def match_document_types_by_name(names: list[str], user: User) -> list[DocumentType]:
    queryset = get_objects_for_user_owner_aware(
        user,
        ["view_documenttype"],
        DocumentType,
    )
    return _match_names_to_queryset(names, queryset, "name")


def match_storage_paths_by_name(names: list[str], user: User) -> list[StoragePath]:
    queryset = get_objects_for_user_owner_aware(
        user,
        ["view_storagepath"],
        StoragePath,
    )
    return _match_names_to_queryset(names, queryset, "name")


def _normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)  # remove punctuation
    s = s.strip()
    return s


def _match_names_to_queryset(names: list[str], queryset, attr: str):
    results = []
    objects = list(queryset)
    object_names = [_normalize(getattr(obj, attr)) for obj in objects]

    for name in names:
        if not name:
            continue
        target = _normalize(name)

        # First try exact match
        if target in object_names:
            index = object_names.index(target)
            matched = objects.pop(index)
            object_names.pop(index)  # keep object list aligned after removal
            results.append(matched)
            continue

        # Fuzzy match fallback
        matches = difflib.get_close_matches(
            target,
            object_names,
            n=1,
            cutoff=MATCH_THRESHOLD,
        )
        if matches:
            index = object_names.index(matches[0])
            matched = objects.pop(index)
            object_names.pop(index)
            results.append(matched)
        else:
            pass
    return results


def extract_unmatched_names(
    names: list[str],
    matched_objects: list,
    attr="name",
) -> list[str]:
    matched_names = {getattr(obj, attr).lower() for obj in matched_objects}
    return [name for name in names if name.lower() not in matched_names]


def auto_match_or_create_tags(
    names_with_confidence: list[dict],
    user: User,
    auto_create_threshold: float = 0.8,
) -> list[Tag]:
    """
    Auto-match or create tags based on confidence scores.

    For each tag with confidence >= threshold, either match existing or auto-create.
    Returns list of matched/created Tag objects.
    """
    from documents.models import Tag

    results = []
    queryset = get_objects_for_user_owner_aware(
        user,
        ["view_tag"],
        Tag,
    )

    for item in names_with_confidence:
        name = item["value"]
        confidence = item["confidence"]

        if not name or confidence < auto_create_threshold:
            continue

        # First try exact match
        normalized_name = _normalize(name)
        existing_tag = None
        for tag in queryset:
            if _normalize(tag.name) == normalized_name:
                existing_tag = tag
                break

        if existing_tag:
            results.append(existing_tag)
            continue

        # Fuzzy match fallback
        objects = list(queryset)
        object_names = [_normalize(tag.name) for tag in objects]

        matches = difflib.get_close_matches(
            normalized_name,
            object_names,
            n=1,
            cutoff=MATCH_THRESHOLD,
        )
        if matches:
            index = object_names.index(matches[0])
            matched = objects[index]
            results.append(matched)
        else:
            # Auto-create new tag
            new_tag = Tag.objects.create(
                name=name,
                owner=user,
            )
            logger.info(f"Auto-created tag '{name}' for user {user}")
            results.append(new_tag)

    return results


def auto_match_or_create_correspondents(
    names_with_confidence: list[dict],
    user: User,
    auto_create_threshold: float = 0.8,
) -> list[Correspondent]:
    """
    Auto-match or create correspondents based on confidence scores.
    """
    from documents.models import Correspondent

    results = []
    queryset = get_objects_for_user_owner_aware(
        user,
        ["view_correspondent"],
        Correspondent,
    )

    for item in names_with_confidence:
        name = item["value"]
        confidence = item["confidence"]

        if not name or confidence < auto_create_threshold:
            continue

        # First try exact match
        normalized_name = _normalize(name)
        existing_corr = None
        for corr in queryset:
            if _normalize(corr.name) == normalized_name:
                existing_corr = corr
                break

        if existing_corr:
            results.append(existing_corr)
            continue

        # Fuzzy match fallback
        objects = list(queryset)
        object_names = [_normalize(corr.name) for corr in objects]

        matches = difflib.get_close_matches(
            normalized_name,
            object_names,
            n=1,
            cutoff=MATCH_THRESHOLD,
        )
        if matches:
            index = object_names.index(matches[0])
            matched = objects[index]
            results.append(matched)
        else:
            # Auto-create new correspondent
            new_corr = Correspondent.objects.create(
                name=name,
                owner=user,
            )
            logger.info(f"Auto-created correspondent '{name}' for user {user}")
            results.append(new_corr)

    return results


def auto_match_or_create_document_types(
    names_with_confidence: list[dict],
    user: User,
    auto_create_threshold: float = 0.8,
) -> list[DocumentType]:
    """
    Auto-match or create document types based on confidence scores.
    """
    from documents.models import DocumentType

    results = []
    queryset = get_objects_for_user_owner_aware(
        user,
        ["view_documenttype"],
        DocumentType,
    )

    for item in names_with_confidence:
        name = item["value"]
        confidence = item["confidence"]

        if not name or confidence < auto_create_threshold:
            continue

        # First try exact match
        normalized_name = _normalize(name)
        existing_dt = None
        for dt in queryset:
            if _normalize(dt.name) == normalized_name:
                existing_dt = dt
                break

        if existing_dt:
            results.append(existing_dt)
            continue

        # Fuzzy match fallback
        objects = list(queryset)
        object_names = [_normalize(dt.name) for dt in objects]

        matches = difflib.get_close_matches(
            normalized_name,
            object_names,
            n=1,
            cutoff=MATCH_THRESHOLD,
        )
        if matches:
            index = object_names.index(matches[0])
            matched = objects[index]
            results.append(matched)
        else:
            # Auto-create new document type
            new_dt = DocumentType.objects.create(
                name=name,
                owner=user,
            )
            logger.info(f"Auto-created document type '{name}' for user {user}")
            results.append(new_dt)

    return results


def auto_match_or_create_storage_paths(
    names_with_confidence: list[dict],
    user: User,
    auto_create_threshold: float = 0.8,
) -> list[StoragePath]:
    """
    Auto-match or create storage paths based on confidence scores.
    """
    from documents.models import StoragePath

    results = []
    queryset = get_objects_for_user_owner_aware(
        user,
        ["view_storagepath"],
        StoragePath,
    )

    for item in names_with_confidence:
        name = item["value"]
        confidence = item["confidence"]

        if not name or confidence < auto_create_threshold:
            continue

        # First try exact match
        normalized_name = _normalize(name)
        existing_sp = None
        for sp in queryset:
            if _normalize(sp.name) == normalized_name:
                existing_sp = sp
                break

        if existing_sp:
            results.append(existing_sp)
            continue

        # Fuzzy match fallback
        objects = list(queryset)
        object_names = [_normalize(sp.name) for sp in objects]

        matches = difflib.get_close_matches(
            normalized_name,
            object_names,
            n=1,
            cutoff=MATCH_THRESHOLD,
        )
        if matches:
            index = object_names.index(matches[0])
            matched = objects[index]
            results.append(matched)
        else:
            # Auto-create new storage path
            new_sp = StoragePath.objects.create(
                name=name,
                owner=user,
            )
            logger.info(f"Auto-created storage path '{name}' for user {user}")
            results.append(new_sp)

    return results
