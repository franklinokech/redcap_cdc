import json
from datetime import timedelta

import requests
from django.utils import timezone

from projects.models import SyncLog, SyncRecordLog


class SyncService:
    def __init__(self, project):
        self.project = project
        self.key_field = project.record_identifier_field

    # =====================================================
    # ENTRY POINT
    # =====================================================
    def run(self, mode="incremental"):
        if mode == "full":
            return self.run_full_sync()
        return self.run_incremental_sync()

    # =====================================================
    # REDCAP HELPERS
    # =====================================================
    def fetch_all_record_ids(self):
        payload = {
            "token": self.project.source_token,
            "content": "record",
            "format": "json",
            "type": "flat",
            "fields[0]": self.key_field,
        }

        response = requests.post(self.project.source_url, data=payload, timeout=60)
        response.raise_for_status()

        data = response.json()

        return list({
            row[self.key_field]
            for row in data
            if self.key_field in row
        })

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
        return list({
            log["record"]
            for log in logs
            if log.get("record")
        })

    # =====================================================
    # LOGGING
    # =====================================================
    def _start_log(self):
        return SyncLog.objects.create(
            project=self.project,
            status=SyncLog.SyncStatus.PENDING,
            started_at=timezone.now(),
        )

    def _finish_log(self, log, success=True, error=None):
        log.ended_at = timezone.now()
        log.status = (
            SyncLog.SyncStatus.SUCCESS
            if success
            else SyncLog.SyncStatus.FAILED
        )

        if error:
            log.details = error

        log.save()
        return log

    def _finalize_sync(self, log):
        log.records_synced = SyncRecordLog.objects.filter(
            sync_log=log,
            status=SyncRecordLog.Status.SUCCESS
        ).count()

        log.records_failed = SyncRecordLog.objects.filter(
            sync_log=log,
            status=SyncRecordLog.Status.FAILED
        ).count()

        # finish log FIRST (sets ended_at)
        log = self._finish_log(
            log,
            success=(log.records_failed == 0)
        )

        # THEN update project checkpoint using the log's ended_at
        self.project.last_sync_timestamp = log.ended_at
        self.project.save(update_fields=["last_sync_timestamp"])

        return log

    # =====================================================
    # TARGET PUSH
    # =====================================================
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

        response.raise_for_status()

        return {
            r[self.key_field]
            for r in records
            if self.key_field in r
        }

    # =====================================================
    # INCREMENTAL SYNC
    # =====================================================
    def run_incremental_sync(self):
        log = self._start_log()

        try:
            overlap = self.project.overlap_minutes
            begin_time = (
                self.project.last_sync_timestamp - timedelta(minutes=overlap)
                if self.project.last_sync_timestamp
                else None
            )

            logs = self.fetch_logs(begin_time)
            record_ids = self.extract_changed_records(logs)

            log.records_expected = len(record_ids)
            log.save()

            if not record_ids:
                # Let _finalize_sync handle timestamp update
                return self._finalize_sync(log)

            record_log_map = {}

            for rid in record_ids:
                record_log_map[rid] = SyncRecordLog.objects.create(
                    sync_log=log,
                    record_id=rid,
                    status=SyncRecordLog.Status.PENDING
                )

            for batch in self._chunk(record_ids):
                try:
                    records = self.fetch_records_by_ids(batch)
                    self.push_to_target(records)

                    for rid in batch:
                        rec_log = record_log_map.get(rid)
                        if rec_log:
                            rec_log.status = SyncRecordLog.Status.SUCCESS
                            rec_log.save()

                except Exception as e:
                    for rid in batch:
                        rec_log = record_log_map.get(rid)
                        if rec_log:
                            rec_log.status = SyncRecordLog.Status.FAILED
                            rec_log.error = str(e)
                            rec_log.save()

            return self._finalize_sync(log)

        except Exception as e:
            return self._finish_log(log, success=False, error=str(e))

    # =====================================================
    # FULL SYNC
    # =====================================================
    def run_full_sync(self):
        log = self._start_log()

        try:
            record_ids = self.fetch_all_record_ids()

            log.records_expected = len(record_ids)
            log.save()

            if not record_ids:
                return self._finalize_sync(log)

            record_log_map = {}

            for rid in record_ids:
                record_log_map[rid] = SyncRecordLog.objects.create(
                    sync_log=log,
                    record_id=rid,
                    status=SyncRecordLog.Status.PENDING
                )

            for batch in self._chunk(record_ids):
                try:
                    records = self.fetch_records_by_ids(batch)
                    self.push_to_target(records)

                    for rid in batch:
                        rec_log = record_log_map.get(rid)
                        if rec_log:
                            rec_log.status = SyncRecordLog.Status.SUCCESS
                            rec_log.save()

                except Exception as e:
                    for rid in batch:
                        rec_log = record_log_map.get(rid)
                        if rec_log:
                            rec_log.status = SyncRecordLog.Status.FAILED
                            rec_log.error = str(e)
                            rec_log.save()

            return self._finalize_sync(log)

        except Exception as e:
            return self._finish_log(log, success=False, error=str(e))