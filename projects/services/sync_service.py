import json
import logging
from datetime import timedelta

import requests
from requests.exceptions import ConnectionError, Timeout, HTTPError

from django.utils import timezone

from projects.models import SyncLog, SyncRecordLog

logger = logging.getLogger("projects")


# =====================================================
# EXCEPTIONS
# =====================================================

class RetryableSyncError(Exception):
    """Transient errors (network, 5xx) → safe to retry"""
    pass


class NonRetryableSyncError(Exception):
    """Bad request / bad data → DO NOT retry"""
    pass


# =====================================================
# SERVICE
# =====================================================

class SyncService:
    def __init__(self, project):
        self.project = project
        self.key_field = project.record_identifier_field

    # =====================================================
    # ENTRY POINT
    # =====================================================

    def run(self, mode="incremental"):
        return (
            self.run_full_sync()
            if mode == "full"
            else self.run_incremental_sync()
        )

    # =====================================================
    # HTTP LAYER (CORE FIXED LOGIC)
    # =====================================================

    def _post(self, url, payload, context=None):
        context = context or {}

        try:
            logger.info(
                "[HTTP REQUEST]",
                extra={
                    "url": url,
                    "context": context,
                }
            )

            response = requests.post(url, data=payload, timeout=60)
            response.raise_for_status()
            return response

        except (ConnectionError, Timeout) as e:
            logger.warning(
                "[HTTP RETRYABLE ERROR]",
                extra={"error": str(e), "context": context},
            )
            raise RetryableSyncError(f"Connection issue: {str(e)}")

        except HTTPError as e:
            response = getattr(e, "response", None)

            status = getattr(response, "status_code", None)
            body = getattr(response, "text", str(e))

            error_payload = {
                "status": status,
                "body": body,
                "context": context,
            }

            if status and status >= 500:
                logger.warning("[HTTP 5XX]", extra=error_payload)
                raise RetryableSyncError(error_payload)

            logger.error("[HTTP 4XX]", extra=error_payload)
            raise NonRetryableSyncError(error_payload)

    def _safe_json(self, response):
        try:
            return response.json()
        except ValueError as e:
            raise NonRetryableSyncError({
                "type": "invalid_json",
                "error": str(e),
                "body": response.text,
            })

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

        response = self._post(
            self.project.source_url,
            payload,
            context={"operation": "fetch_all_record_ids"},
        )

        data = self._safe_json(response)

        return list({
            row[self.key_field]
            for row in data
            if self.key_field in row
        })

    def fetch_records_by_ids(self, record_ids):
        payload = {
            "token": self.project.source_token,
            "content": "record",
            "format": "json",
            "type": "flat",
        }

        for i, rid in enumerate(record_ids):
            payload[f"records[{i}]"] = rid

        response = self._post(
            self.project.source_url,
            payload,
            context={"operation": "fetch_records_by_ids", "count": len(record_ids)},
        )

        return self._safe_json(response)

    def fetch_logs(self, begin_time=None):
        payload = {
            "token": self.project.source_token,
            "content": "log",
            "format": "json",
        }

        if begin_time:
            payload["beginTime"] = begin_time.strftime("%Y-%m-%d %H:%M")

        response = self._post(
            self.project.source_url,
            payload,
            context={"operation": "fetch_logs"},
        )

        return self._safe_json(response)

    def extract_changed_records(self, logs):
        return list({
            log["record"]
            for log in logs
            if log.get("record")
        })

    def _chunk(self, items):
        size = self.project.chunk_size or 100
        for i in range(0, len(items), size):
            yield items[i:i + size]

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
            log.details = json.dumps(error, default=str)

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

        log = self._finish_log(
            log,
            success=(log.records_failed == 0)
        )

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

        response = self._post(
            self.project.target_url,
            payload,
            context={"operation": "push_to_target", "count": len(records)},
        )

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
                return self._finalize_sync(log)

            record_log_map = {
                rid: SyncRecordLog.objects.create(
                    sync_log=log,
                    record_id=rid,
                    status=SyncRecordLog.Status.PENDING
                )
                for rid in record_ids
            }

            for batch in self._chunk(record_ids):
                records = self.fetch_records_by_ids(batch)
                self.push_to_target(records)

                for rid in batch:
                    rec_log = record_log_map.get(rid)
                    if rec_log:
                        rec_log.status = SyncRecordLog.Status.SUCCESS
                        rec_log.save()

            return self._finalize_sync(log)

        except RetryableSyncError as e:
            raise

        except NonRetryableSyncError as e:
            return self._finish_log(log, success=False, error=e)

        except Exception as e:
            raise RetryableSyncError({"unexpected_error": str(e)})

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

            record_log_map = {
                rid: SyncRecordLog.objects.create(
                    sync_log=log,
                    record_id=rid,
                    status=SyncRecordLog.Status.PENDING
                )
                for rid in record_ids
            }

            for batch in self._chunk(record_ids):
                records = self.fetch_records_by_ids(batch)
                self.push_to_target(records)

                for rid in batch:
                    rec_log = record_log_map.get(rid)
                    if rec_log:
                        rec_log.status = SyncRecordLog.Status.SUCCESS
                        rec_log.save()

            return self._finalize_sync(log)

        except RetryableSyncError:
            raise

        except NonRetryableSyncError as e:
            return self._finish_log(log, success=False, error=e)

        except Exception as e:
            raise RetryableSyncError({"unexpected_error": str(e)})