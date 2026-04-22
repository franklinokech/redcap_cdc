from django.contrib import admin
from projects.models import RedcapProject, SyncLog

@admin.register(RedcapProject)
class RedcapProjectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "source_project_id",
        "target_project_id",
        "is_active",
        "created_at",
    )

    list_filter = ("is_active",)

    search_fields = (
        "name",
        "updated_at",
        "last_sync_timestamp",
    )

@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "status",
        "records_synced",
        "started_at",
        "ended_at",
        "timestamp",
    )

    list_filter = ("status", "project")

    search_fields = ("project__name", "details")

    readonly_fields = (
        "timestamp",
        "started_at",
        "ended_at",
        "created_at",
        "updated_at",
    )