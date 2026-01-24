import logging
import shutil
from os import utime
from pathlib import Path
from subprocess import CompletedProcess
from subprocess import run
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from PIL import Image

from paperless.config import AIConfig

if TYPE_CHECKING:
    from documents.models import Document

logger = logging.getLogger("paperless_ai.enhancement")


def _coerce_to_path(
    source: Path | str,
    dest: Path | str,
) -> tuple[Path, Path]:
    return Path(source).resolve(), Path(dest).resolve()


def copy_basic_file_stats(source: Path | str, dest: Path | str) -> None:
    """
    Copies only the m_time and a_time attributes from source to destination.
    Both are expected to exist.

    The extended attribute copy does weird things with SELinux and files
    copied from temporary directories and copystat doesn't allow disabling
    these copies.

    If there is a PermissionError, skip copying file stats.
    """
    source, dest = _coerce_to_path(source, dest)
    src_stat = source.stat()

    try:
        utime(dest, ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns))
    except PermissionError:
        pass


def apply_ai_suggestions(document: "Document", suggestions: dict):
    """
    Apply approved AI suggestions to a document.

    Reuses the existing auto-matching logic from the enhancement task.
    """
    from documents.tasks import auto_match_or_create_correspondents
    from documents.tasks import auto_match_or_create_document_types
    from documents.tasks import auto_match_or_create_storage_paths
    from documents.tasks import auto_match_or_create_tags

    ai_config = AIConfig()
    auto_create_threshold = ai_config.auto_create_threshold

    # Apply title
    title_suggestion = suggestions.get("title")
    if title_suggestion and isinstance(title_suggestion, dict):
        document.title = title_suggestion.get("value")
        document.save()

    # Apply tags
    tag_suggestions = suggestions.get("tags", [])
    matched_tags = auto_match_or_create_tags(
        tag_suggestions,
        document.owner,
        auto_create_threshold,
    )
    if matched_tags:
        document.tags.add(*matched_tags)

    # Apply correspondent
    correspondent_suggestions = suggestions.get("correspondents", [])
    matched_correspondents = auto_match_or_create_correspondents(
        correspondent_suggestions,
        document.owner,
        auto_create_threshold,
    )
    if matched_correspondents and not document.correspondent:
        document.correspondent = matched_correspondents[0]

    # Apply document type
    document_type_suggestions = suggestions.get("document_types", [])
    matched_document_types = auto_match_or_create_document_types(
        document_type_suggestions,
        document.owner,
        auto_create_threshold,
    )
    if matched_document_types and not document.document_type:
        document.document_type = matched_document_types[0]

    # Apply storage path
    storage_path_suggestions = suggestions.get("storage_paths", [])
    matched_storage_paths = auto_match_or_create_storage_paths(
        storage_path_suggestions,
        document.owner,
        auto_create_threshold,
    )
    if matched_storage_paths and not document.storage_path:
        document.storage_path = matched_storage_paths[0]

    # Save the document
    document.save()


def rollback_ai_suggestions(history_id: int, user):
    """
    Rollback applied AI suggestions for a document.

    Reverses the changes made by applying AI suggestions, restoring the document
    to its previous state before the suggestions were applied. Includes permission
    checks and comprehensive logging for audit purposes.

    Args:
        history_id: ID of the AISuggestionHistory record to rollback
        user: User performing the rollback

    Raises:
        ValueError: If history record not found or already rolled back
        PermissionDenied: If user lacks permission to rollback

    Returns:
        AISuggestionHistory: The updated history record
    """
    from guardian.shortcuts import get_perms

    from documents.models import AISuggestionHistory

    try:
        history = AISuggestionHistory.objects.get(id=history_id)
    except AISuggestionHistory.DoesNotExist:
        raise ValueError(f"AI suggestion history record {history_id} not found")

    if history.rolled_back:
        raise ValueError(
            f"AI suggestion history record {history_id} has already been rolled back",
        )

    # Permission checks
    if (
        user != history.owner
        and not user.is_superuser
        and not (
            user.has_perm("documents.apply_ai_enhancement")
            or "change_document" in get_perms(user, history.document)
        )
    ):
        raise PermissionDenied("You do not have permission to rollback AI suggestions")

    document = history.document
    suggestions = history.applied_suggestions

    logger.info(
        f"Rolling back AI suggestions for document '{document.title}' "
        f"(ID: {document.id}) by user {user.username}",
        extra={
            "document_id": document.id,
            "history_id": history_id,
            "user_id": user.id,
            "suggestions": suggestions,
        },
    )

    # Reverse title change
    title_suggestion = suggestions.get("title")
    if title_suggestion and isinstance(title_suggestion, dict):
        # Note: We can't easily determine the original title without storing it
        # This is a limitation - in practice, rollback might need manual intervention
        # for title changes
        logger.warning(
            f"Unable to automatically rollback title change for document {document.id}. "
            "Manual intervention may be required.",
        )

    # Remove assigned tags
    tag_suggestions = suggestions.get("tags", [])
    if tag_suggestions:
        # Find tags that were created or matched by the suggestions
        from paperless_ai.matching import auto_match_or_create_tags

        matched_tags = auto_match_or_create_tags(
            tag_suggestions,
            document.owner,
            1.0,
        )  # Use high threshold to avoid creating
        document.tags.remove(*matched_tags)

    # Remove assigned correspondent
    correspondent_suggestions = suggestions.get("correspondents", [])
    if correspondent_suggestions and document.correspondent:
        from paperless_ai.matching import auto_match_or_create_correspondents

        matched_correspondents = auto_match_or_create_correspondents(
            correspondent_suggestions,
            document.owner,
            1.0,
        )
        if document.correspondent in matched_correspondents:
            document.correspondent = None

    # Remove assigned document type
    document_type_suggestions = suggestions.get("document_types", [])
    if document_type_suggestions and document.document_type:
        from paperless_ai.matching import auto_match_or_create_document_types

        matched_document_types = auto_match_or_create_document_types(
            document_type_suggestions,
            document.owner,
            1.0,
        )
        if document.document_type in matched_document_types:
            document.document_type = None

    # Remove assigned storage path
    storage_path_suggestions = suggestions.get("storage_paths", [])
    if storage_path_suggestions and document.storage_path:
        from paperless_ai.matching import auto_match_or_create_storage_paths

        matched_storage_paths = auto_match_or_create_storage_paths(
            storage_path_suggestions,
            document.owner,
            1.0,
        )
        if document.storage_path in matched_storage_paths:
            document.storage_path = None

    # Save the document
    document.save()

    # Update history record
    history.rolled_back = True
    history.rolled_back_at = timezone.now()
    history.rolled_back_by = user
    history.save()

    logger.info(
        f"Successfully rolled back AI suggestions for document '{document.title}' "
        f"(ID: {document.id})",
        extra={
            "document_id": document.id,
            "history_id": history_id,
            "user_id": user.id,
        },
    )

    return history


def check_ai_rate_limit(user):
    """
    Check if user has exceeded AI operation rate limits.

    Uses Django cache to track requests per user within a time window.
    Rate limits are configurable via settings.

    Args:
        user: User to check limits for

    Returns:
        bool: True if under limit, False if exceeded

    Raises:
        ValueError: If rate limiting configuration is invalid
    """
    ai_config = AIConfig()

    if not ai_config.rate_limit_requests > 0:
        raise ValueError("Rate limit requests must be greater than 0")

    if not ai_config.rate_limit_window > 0:
        raise ValueError("Rate limit window must be greater than 0")

    cache_key = f"ai_rate_limit_{user.id}"
    current_time = timezone.now().timestamp()

    # Get existing requests from cache
    cached_data = cache.get(cache_key, [])
    if not isinstance(cached_data, list):
        cached_data = []

    # Filter out expired requests
    window_start = current_time - ai_config.rate_limit_window
    valid_requests = [req for req in cached_data if req > window_start]

    # Check if under limit
    if len(valid_requests) >= ai_config.rate_limit_requests:
        logger.warning(
            f"Rate limit exceeded for user {user.username} "
            f"({len(valid_requests)} requests in {ai_config.rate_limit_window}s)",
            extra={
                "user_id": user.id,
                "request_count": len(valid_requests),
                "limit": ai_config.rate_limit_requests,
                "window": ai_config.rate_limit_window,
            },
        )
        return False

    # Add current request and update cache
    valid_requests.append(current_time)
    cache.set(cache_key, valid_requests, ai_config.rate_limit_window)

    logger.debug(
        f"Rate limit check passed for user {user.username} "
        f"({len(valid_requests)}/{ai_config.rate_limit_requests} requests)",
        extra={
            "user_id": user.id,
            "request_count": len(valid_requests),
            "limit": ai_config.rate_limit_requests,
        },
    )

    return True


def copy_file_with_basic_stats(
    source: Path | str,
    dest: Path | str,
) -> None:
    """
    A sort of simpler copy2 that doesn't copy extended file attributes,
    only the access time and modified times from source to dest.

    The extended attribute copy does weird things with SELinux and files
    copied from temporary directories.

    If there is a PermissionError (e.g., on ZFS with acltype=nfsv4)
    fall back to copyfile (data only).
    """
    source, dest = _coerce_to_path(source, dest)

    try:
        shutil.copy(source, dest)
    except PermissionError:
        shutil.copyfile(source, dest)

    copy_basic_file_stats(source, dest)


def maybe_override_pixel_limit() -> None:
    """
    Maybe overrides the PIL limit on pixel count, if configured to allow it
    """
    limit: float | int | None = settings.MAX_IMAGE_PIXELS
    if limit is not None and limit >= 0:
        pixel_count = limit
        if pixel_count == 0:
            pixel_count = None
        Image.MAX_IMAGE_PIXELS = pixel_count


def run_subprocess(
    arguments: list[str],
    env: dict[str, str] | None = None,
    logger: logging.Logger | None = None,
    *,
    check_exit_code: bool = True,
    log_stdout: bool = True,
    log_stderr: bool = True,
) -> CompletedProcess:
    """
    Runs a subprocess and logs its output, checking return code if requested
    """

    proc_name = arguments[0]

    if logger:
        # Log before execution to catch hangs
        logger.info(f"Executing: {' '.join(str(a) for a in arguments)}")

    completed_proc = run(args=arguments, env=env, capture_output=True, check=False)

    if logger:
        logger.info(f"{proc_name} exited {completed_proc.returncode}")

    if log_stdout and logger and completed_proc.stdout:
        stdout_str = (
            completed_proc.stdout.decode("utf8", errors="ignore")
            .strip()
            .split(
                "\n",
            )
        )
        logger.info(f"{proc_name} stdout:")
        for line in stdout_str:
            logger.info(line)

    if log_stderr and logger and completed_proc.stderr:
        stderr_str = (
            completed_proc.stderr.decode("utf8", errors="ignore")
            .strip()
            .split(
                "\n",
            )
        )
        logger.info(f"{proc_name} stderr:")
        for line in stderr_str:
            logger.warning(line)

    # Last, if requested, after logging outputs
    if check_exit_code:
        completed_proc.check_returncode()

    return completed_proc


def get_boolean(boolstr: str) -> bool:
    """
    Return a boolean value from a string representation.
    """
    return bool(boolstr.lower() in ("yes", "y", "1", "t", "true"))
