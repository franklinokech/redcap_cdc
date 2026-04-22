from rest_framework import serializers
from projects.models import SyncLog

class SyncLogSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )

    class Meta:
        model = SyncLog
        fields = [
            "id",
            "project",
            "status",
            "status_display",
            "records_synced",
            "details",
            "timestamp",
            "started_at",
            "ended_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "project",
            "timestamp",
            "started_at",
            "ended_at",
            "created_at",
            "updated_at",
        ]