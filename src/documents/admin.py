from django.conf import settings
from django.contrib import admin
from django.utils import timezone
from guardian.admin import GuardedModelAdmin
from treenode.admin import TreeNodeModelAdmin

from documents.models import AIReviewQueue
from documents.models import AISuggestionHistory
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import Note
from documents.models import PaperlessTask
from documents.models import SavedView
from documents.models import SavedViewFilterRule
from documents.models import ShareLink
from documents.models import StoragePath
from documents.models import Tag
from documents.tasks import update_document_parent_tags

if settings.AUDIT_LOG_ENABLED:
    from auditlog.admin import LogEntryAdmin
    from auditlog.models import LogEntry


class CorrespondentAdmin(GuardedModelAdmin):
    list_display = ("name", "match", "matching_algorithm")
    list_filter = ("matching_algorithm",)
    list_editable = ("match", "matching_algorithm")


class TagAdmin(GuardedModelAdmin, TreeNodeModelAdmin):
    list_display = ("name", "color", "match", "matching_algorithm")
    list_filter = ("matching_algorithm",)
    list_editable = ("color", "match", "matching_algorithm")
    search_fields = ("color", "name")

    def save_model(self, request, obj, form, change):
        old_parent = None
        if change and obj.pk:
            tag = Tag.objects.get(pk=obj.pk)
            old_parent = tag.get_parent() if tag else None

        super().save_model(request, obj, form, change)

        # sync parent tags on documents if changed
        new_parent = obj.get_parent()
        if new_parent and old_parent != new_parent:
            update_document_parent_tags(obj, new_parent)


class DocumentTypeAdmin(GuardedModelAdmin):
    list_display = ("name", "match", "matching_algorithm")
    list_filter = ("matching_algorithm",)
    list_editable = ("match", "matching_algorithm")


class DocumentAdmin(GuardedModelAdmin):
    search_fields = ("correspondent__name", "title", "content", "tags__name")
    readonly_fields = (
        "added",
        "modified",
        "mime_type",
        "filename",
        "checksum",
        "archive_filename",
        "archive_checksum",
        "original_filename",
        "deleted_at",
    )

    list_display_links = ("title",)

    list_display = ("id", "title", "mime_type", "filename", "archive_filename")

    list_filter = (
        ("mime_type"),
        ("archive_serial_number", admin.EmptyFieldListFilter),
        ("archive_filename", admin.EmptyFieldListFilter),
    )

    filter_horizontal = ("tags",)

    ordering = ["-id"]

    date_hierarchy = "created"

    def has_add_permission(self, request):
        return False

    def created_(self, obj):
        return obj.created.date().strftime("%Y-%m-%d")

    created_.short_description = "Created"

    def get_queryset(self, request):  # pragma: no cover
        """
        Include trashed documents
        """
        return Document.global_objects.all()

    def delete_queryset(self, request, queryset):
        from documents import index

        with index.open_index_writer() as writer:
            for o in queryset:
                index.remove_document(writer, o)

        super().delete_queryset(request, queryset)

    def delete_model(self, request, obj):
        from documents import index

        index.remove_document_from_index(obj)
        super().delete_model(request, obj)

    def save_model(self, request, obj, form, change):
        from documents import index

        index.add_or_update_document(obj)
        super().save_model(request, obj, form, change)


class RuleInline(admin.TabularInline):
    model = SavedViewFilterRule


class SavedViewAdmin(GuardedModelAdmin):
    list_display = ("name", "owner")

    inlines = [RuleInline]

    def get_queryset(self, request):  # pragma: no cover
        return super().get_queryset(request).select_related("owner")


class StoragePathInline(admin.TabularInline):
    model = StoragePath


class StoragePathAdmin(GuardedModelAdmin):
    list_display = ("name", "path", "match", "matching_algorithm")
    list_filter = ("path", "matching_algorithm")
    list_editable = ("path", "match", "matching_algorithm")


class TaskAdmin(admin.ModelAdmin):
    list_display = ("task_id", "task_file_name", "task_name", "date_done", "status")
    list_filter = ("status", "date_done", "task_name")
    search_fields = ("task_name", "task_id", "status", "task_file_name")
    readonly_fields = (
        "task_id",
        "task_file_name",
        "task_name",
        "status",
        "date_created",
        "date_started",
        "date_done",
        "result",
    )


class NotesAdmin(GuardedModelAdmin):
    list_display = ("user", "created", "note", "document")
    list_filter = ("created", "user")
    list_display_links = ("created",)
    raw_id_fields = ("document",)
    search_fields = ("document__title",)

    def get_queryset(self, request):  # pragma: no cover
        return (
            super()
            .get_queryset(request)
            .select_related("user", "document__correspondent")
        )


class ShareLinksAdmin(GuardedModelAdmin):
    list_display = ("created", "expiration", "document")
    list_filter = ("created", "expiration", "owner")
    list_display_links = ("created",)
    raw_id_fields = ("document",)

    def get_queryset(self, request):  # pragma: no cover
        return super().get_queryset(request).select_related("document__correspondent")


class CustomFieldsAdmin(GuardedModelAdmin):
    fields = ("name", "created", "data_type")
    readonly_fields = ("created", "data_type")
    list_display = ("name", "created", "data_type")
    list_filter = ("created", "data_type")


class CustomFieldInstancesAdmin(GuardedModelAdmin):
    fields = ("field", "document", "created", "value")
    readonly_fields = ("field", "document", "created", "value")
    list_display = ("field", "document", "value", "created")
    search_fields = ("document__title",)
    list_filter = ("created", "field")

    def get_queryset(self, request):  # pragma: no cover
        return (
            super()
            .get_queryset(request)
            .select_related("field", "document__correspondent")
        )


class AIReviewQueueAdmin(GuardedModelAdmin):
    list_display = (
        "document",
        "status",
        "created_at",
        "reviewed_by",
        "owner",
        "min_confidence",
    )
    list_filter = ("status", "created_at", "reviewed_at")
    search_fields = ("document__title", "reviewed_by__username")
    readonly_fields = ("created_at", "updated_at")

    def min_confidence(self, obj):
        """Display the minimum confidence score for the review item."""
        if obj.confidence_scores:
            scores = [
                score
                for score in obj.confidence_scores.values()
                if isinstance(score, (int, float))
            ]
            return min(scores) if scores else None
        return None

    min_confidence.short_description = "Min Confidence"

    actions = ["bulk_approve", "bulk_reject"]

    def bulk_approve(self, request, queryset):
        """Bulk approve selected review items."""
        count = queryset.filter(status=AIReviewQueue.Status.PENDING).update(
            status=AIReviewQueue.Status.APPROVED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"Approved {count} AI review items.")

    bulk_approve.short_description = "Approve selected AI reviews"

    def bulk_reject(self, request, queryset):
        """Bulk reject selected review items."""
        count = queryset.filter(status=AIReviewQueue.Status.PENDING).update(
            status=AIReviewQueue.Status.REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"Rejected {count} AI review items.")

    bulk_reject.short_description = "Reject selected AI reviews"


class AISuggestionHistoryAdmin(GuardedModelAdmin):
    list_display = (
        "document",
        "applied_at",
        "applied_by",
        "rolled_back",
        "rolled_back_at",
        "rolled_back_by",
        "owner",
    )
    list_filter = ("rolled_back", "applied_at", "rolled_back_at")
    search_fields = (
        "document__title",
        "applied_by__username",
        "rolled_back_by__username",
    )
    readonly_fields = ("applied_at", "rolled_back_at")
    actions = ["bulk_rollback"]

    def bulk_rollback(self, request, queryset):
        """Bulk rollback selected history items."""
        from documents.utils import rollback_ai_suggestions

        count = 0
        errors = []
        for history in queryset.filter(rolled_back=False):
            try:
                rollback_ai_suggestions(history.id, request.user)
                count += 1
            except Exception as e:
                errors.append(f"Failed to rollback {history.id}: {e}")

        if count:
            self.message_user(request, f"Rolled back {count} AI suggestion histories.")
        if errors:
            self.message_user(request, f"Errors: {'; '.join(errors)}", level="ERROR")

    bulk_rollback.short_description = "Rollback selected AI suggestions"


admin.site.register(Correspondent, CorrespondentAdmin)
admin.site.register(Tag, TagAdmin)
admin.site.register(DocumentType, DocumentTypeAdmin)
admin.site.register(Document, DocumentAdmin)
admin.site.register(SavedView, SavedViewAdmin)
admin.site.register(StoragePath, StoragePathAdmin)
admin.site.register(PaperlessTask, TaskAdmin)
admin.site.register(Note, NotesAdmin)
admin.site.register(ShareLink, ShareLinksAdmin)
admin.site.register(CustomField, CustomFieldsAdmin)
admin.site.register(CustomFieldInstance, CustomFieldInstancesAdmin)
admin.site.register(AIReviewQueue, AIReviewQueueAdmin)
admin.site.register(AISuggestionHistory, AISuggestionHistoryAdmin)

if settings.AUDIT_LOG_ENABLED:

    class LogEntryAUDIT(LogEntryAdmin):
        def has_delete_permission(self, request, obj=None):
            return False

    admin.site.unregister(LogEntry)
    admin.site.register(LogEntry, LogEntryAUDIT)
