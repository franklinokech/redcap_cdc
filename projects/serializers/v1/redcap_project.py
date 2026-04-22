from rest_framework import serializers
from projects.models import  RedcapProject

class RedcapProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = RedcapProject
        fields = [
            "id",
            "name",
            "source_project_id",
            "source_url",
            "target_project_id",
            "target_url",
            "last_sync_timestamp",
            "overlap_minutes",
            "chunk_size",
            "is_active",
            "created_at",
            "updated_at",
        ]

        read_only_fields = ["created_at", "updated_at", "last_sync_timestamp"]


class RedcapProjectWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = RedcapProject
        fields = [
            "name",
            "source_project_id",
            "source_url",
            "source_token",
            "target_project_id",
            "target_url",
            "target_token",
            "overlap_minutes",
            "chunk_size",
            "created_at",
            "updated_at",
            "is_active",
        ]