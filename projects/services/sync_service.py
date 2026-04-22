import json
from datetime import timedelta

import requests
from django.utils import timezone
from projects.models import SyncLog

class SyncService:
    def __init__(self, project):
        self.project = project
        self.key_field = project.record_identifier_field

    def run(self, mode="incremental"):
        if mode == "full":
            return self.run_full_sync()
        return self.run_incremental_sync()

    def fetch_all_record_ids(self):
        payload = {
            "token": self.project.source_token,
            "content": "record",
            "format": "json",
            "type": "flat",
            "fields[0]": self.key_field,
        }

        response = requests.post(
            self.project.source_url,
            data=payload,
            timeout=60
        )
        response.raise_for_status()

        data = response.json()

        return [
            row[self.key_field]
            for row in data
            if self.key_field in row
        ]

    def _chunk(self, items):
        size = self.project.chunk_size
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def fetch_records_by_ids(self, record_ids):
        payload = {
            "token": self.project.source_token,
            "content": "record",
            "format": "json",
            "type": "flat",
        }

        for i, rid in enumerate(record_ids):
            payload[f"records[{i}]"] = rid

        response = requests.post(self.project.source_url, data=payload, timeout=60)
        response.raise_for_status()

        return response.json()

    def _start_log(self):
        return SyncLog.objects.create(
            project=self.project,
            status=SyncLog.SyncStatus.PENDING,
            started_at=timezone.now(),
        )
    def fetch_logs(self, begin_time=None):
        payload = {
            "token": self.project.source_token,
            "content": "log",
            "format": "json",
        }

        if begin_time:
            payload["beginTime"] = begin_time.strftime("%Y-%m-%d %H:%M")

        response = requests.post(self.project.source_url, data=payload, timeout=60)
        response.raise_for_status()

        return response.json()

    def extract_changed_records(self, logs):
        record_ids = set()

        for log in logs:
            if log.get("record"):
                record_ids.add(log["record"])

        return list(record_ids)

    def _finish_log(self, log, count, success=True, error=None):
        log.ended_at = timezone.now()
        log.records_synced = count

        if success:
            log.status = SyncLog.SyncStatus.SUCCESS
        else:
            log.status = SyncLog.SyncStatus.FAILED
            log.details = error or "Unknown error"

        log.save()
        return log

    def push_to_target(self, records):
        payload = {
            "token": self.project.target_token,
            "content": "record",
            "action": "import",
            "format": "json",
            "type": "flat",
            "overwriteBehavior": "normal",
            "data": json.dumps(records),
        }

        response = requests.post(
            self.project.target_url,
            data=payload,
            timeout=60
        )

        # only raise AFTER we see error details
        response.raise_for_status()

        return len(records)

    def run_incremental_sync(self):
        log = self._start_log()

        try:
            cutoff_time = timezone.now()

            if self.project.last_sync_timestamp:
                begin_time = self.project.last_sync_timestamp - timedelta(minutes=1)
            else:
                begin_time = None

            logs = self.fetch_logs(begin_time)
            record_ids = self.extract_changed_records(logs)

            if not record_ids:
                self.project.last_sync_timestamp = cutoff_time
                self.project.save()
                return self._finish_log(log, 0, success=True)

            total_synced = 0

            for batch in self._chunk(record_ids):
                records = self.fetch_records_by_ids(batch)
                total_synced += self.push_to_target(records)

            self.project.last_sync_timestamp = cutoff_time
            self.project.save()

            return self._finish_log(log, total_synced, success=True)

        except Exception as e:
            return self._finish_log(log, 0, success=False, error=str(e))




