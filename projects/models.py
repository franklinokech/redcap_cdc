from django.db import models
from django.utils.translation import gettext_lazy as _

class RedcapProject(models.Model):
    name = models.CharField(max_length=255, unique=True)
    source_project_id = models.CharField(max_length=50)
    record_identifier_field = models.CharField(
        max_length=100,
        default="record_id"
    )
    source_url = models.URLField(help_text="e.g https://site-a.edu/redcap/api/")
    source_token = models.CharField(max_length=255)
    target_project_id = models.CharField(max_length=50)
    target_url = models.URLField(help_text="e.g https://central-hub.edu/redcap/api/")
    target_token = models.CharField(max_length=255)
    last_sync_timestamp = models.DateTimeField(null=True, blank=True)
    overlap_minutes = models.PositiveIntegerField(default=1)
    chunk_size = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class SyncLog(models.Model):
    class SyncStatus(models.TextChoices):
        PENDING = "PE", _("Pending")
        SUCCESS = "SU", _("Success")
        FAILED = "FA", _("Failed")

    project = models.ForeignKey(RedcapProject, on_delete=models.CASCADE, related_name="logs")
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=2,
        choices=SyncStatus,
        default=SyncStatus.PENDING
    )
    records_synced = models.PositiveIntegerField(default=0)
    details = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        ordering = ['-timestamp']

