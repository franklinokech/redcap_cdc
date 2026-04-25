from django.db import models
from django.conf import settings
from django.utils import timezone

from projects.models import RedcapProject


class ValidationRun(models.Model):
    """Track validation runs/sessions"""
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    run_id = models.CharField(max_length=100, unique=True, db_index=True)
    project = models.ForeignKey(RedcapProject, on_delete=models.CASCADE, related_name='validation_runs')
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(choices=Status.choices, default=Status.PENDING, max_length=20)
    total_records = models.IntegerField(default=0)
    records_with_errors = models.IntegerField(default=0)
    total_errors = models.IntegerField(default=0)
    total_warnings = models.IntegerField(default=0)

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    config = models.JSONField(default=dict)
    error_log = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['run_id']),
        ]

    def __str__(self):
        return f"Run {self.run_id} - {self.project.name}"
    @property
    def quality_score(self):
        if self.total_records == 0:
            return 0
        return round(((self.total_records - self.records_with_errors) / self.total_records) * 100, 2)


class ValidationIssue(models.Model):
    """Individual validation issues"""
    class Severity(models.TextChoices):
        ERROR = 'error', 'Error'
        WARNING = 'warning', 'Warning'
        INFO = 'info', 'Info'


    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        IN_REVIEW = 'in_review', 'In Review'
        RESOLVED = 'resolved', 'Resolved'
        IGNORED = 'ignored', 'Ignored'

    project = models.ForeignKey(RedcapProject, on_delete=models.CASCADE, related_name='issues')
    validation_run = models.ForeignKey(ValidationRun, on_delete=models.CASCADE, related_name='issues')
    record_id = models.CharField(max_length=100, db_index=True)
    field_name = models.CharField(max_length=100, db_index=True)
    severity = models.CharField(max_length=20, choices=Severity.choices)
    rule_name = models.CharField(max_length=100)
    message = models.TextField()
    actual_value = models.TextField(blank=True)
    expected_value = models.TextField(blank=True)
    expected_format = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default='open')
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='assigned_issues')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='resolved_issues')
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['severity', '-created_at']
        indexes = [
            models.Index(fields=['project', 'record_id']),
            models.Index(fields=['project', 'status', 'assigned_to']),
            models.Index(fields=['project', 'severity']),
        ]

    def __str__(self):
        return f"{self.get_severity_display()}: {self.record_id}.{self.field_name}"

    def resolve(self, user, note=''):
        self.status = self.Status.RESOLVED
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.resolution_note = note
        self.save()

class RecordSummary(models.Model):
    """Denormalized summary per record for quick queries"""
    project = models.ForeignKey(RedcapProject, on_delete=models.CASCADE, related_name='record_summaries')
    record_id = models.CharField(max_length=100, db_index=True)
    warning_count = models.IntegerField(default=0)
    has_errors = models.BooleanField(default=False, db_index=True)
    is_valid = models.BooleanField(default=True)
    last_validated_at = models.DateTimeField(auto_now=True)
    assigned_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = [['project', 'record_id']]
        indexes = [
            models.Index(fields=['project', 'has_errors']),
            models.Index(fields=['project', 'assigned_user']),
        ]

    def refresh(self):
        """Refresh counts from open issues"""
        open_issues = ValidationIssue.objects.filter(
            project=self.project,
            record_id=self.record_id,
            status__in=['open', 'in_review']
        )

        self.error_count = open_issues.filter(severity='error').count()
        self.warning_count = open_issues.filter(severity='warning').count()
        self.has_errors = self.error_count > 0
        self.is_valid = not self.has_errors
        self.save()