import math
import logging

from celery import shared_task
from django.utils import timezone
from django.db import models

from projects.models import RedcapProject, SyncLog, SyncRecordLog
from projects.services.sync_service import SyncService
from projects.services.sync_service import (
    RetryableSyncError,
    NonRetryableSyncError,
)

logger = logging.getLogger("projects")


# =========================================================
# HELPERS
# =========================================================

def _chunk_size(project):
    return max(project.chunk_size or 100, 1)


def _finalize_log(log: SyncLog, project: RedcapProject):
    if log.ended_at:
        return

    log.refresh_from_db()

    if 0 < log.total_batches <= log.completed_batches:
        status = (
            SyncLog.SyncStatus.SUCCESS
            if log.records_failed == 0
            else SyncLog.SyncStatus.FAILED
        )

        now = timezone.now()

        logger.info({
            "event": "sync.finalize",
            "log_id": log.pk,
            "status": status,
            "synced": log.records_synced,
            "failed": log.records_failed,
            "ended_at": now.isoformat(),
        })

        log.status = status
        log.ended_at = now
        log.save(update_fields=["status", "ended_at"])

        project.last_sync_timestamp = now
        project.save(update_fields=["last_sync_timestamp"])


# =========================================================
# FULL SYNC
# =========================================================

@shared_task
def run_full_sync_task(project_id):
    project = RedcapProject.objects.get(pk=project_id)
    service = SyncService(project)

    logger.info({
        "event": "sync.full.start",
        "project_id": project_id,
    })

    log = service._start_log()

    record_ids = service.fetch_all_record_ids()
    chunk_size = _chunk_size(project)

    log.records_expected = len(record_ids)
    log.total_batches = math.ceil(len(record_ids) / chunk_size)
    log.completed_batches = 0
    log.save()

    for i, batch in enumerate(service._chunk(record_ids), start=1):
        logger.info({
            "event": "sync.full.batch.queued",
            "log_id": log.pk,
            "batch": i,
            "size": len(batch),
        })
        process_batch_task.delay(log.pk, batch)

    return log.pk


# =========================================================
# INCREMENTAL SYNC
# =========================================================

@shared_task
def run_incremental_sync_task(project_id):
    project = RedcapProject.objects.get(pk=project_id)
    service = SyncService(project)

    logger.info({
        "event": "sync.incremental.start",
        "project_id": project_id,
    })

    log = service._start_log()

    begin_time = project.last_sync_timestamp

    logger.info({
        "event": "sync.incremental.state",
        "project_id": project_id,
        "last_sync": begin_time.isoformat() if begin_time else None,
    })

    logs = service.fetch_logs(begin_time)
    record_ids = service.extract_changed_records(logs)

    logger.info({
        "event": "sync.incremental.changes",
        "project_id": project_id,
        "changed_records": len(record_ids),
    })

    chunk_size = _chunk_size(project)

    if not record_ids:
        now = timezone.now()

        log.status = SyncLog.SyncStatus.SUCCESS
        log.ended_at = now
        log.save()

        project.last_sync_timestamp = now
        project.save(update_fields=["last_sync_timestamp"])

        logger.info({
            "event": "sync.incremental.end",
            "log_id": log.pk,
            "status": "no_changes",
        })

        return log.pk

    log.records_expected = len(record_ids)
    log.total_batches = math.ceil(len(record_ids) / chunk_size)
    log.completed_batches = 0
    log.save()

    for i, batch in enumerate(service._chunk(record_ids), start=1):
        logger.info({
            "event": "sync.incremental.batch.queued",
            "log_id": log.pk,
            "batch": i,
        })
        process_batch_task.delay(log.pk, batch)

    return log.pk


# =========================================================
# BATCH PROCESSING (CRITICAL PART)
# =========================================================

@shared_task(
    bind=True,
    autoretry_for=(RetryableSyncError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 10},
)
def process_batch_task(self, log_pk, batch):
    log = SyncLog.objects.get(pk=log_pk)
    project = log.project
    service = SyncService(project)

    logger.info({
        "event": "sync.batch.start",
        "log_id": log_pk,
        "task_id": self.request.id,
        "size": len(batch),
    })

    try:
        records = service.fetch_records_by_ids(batch)
        synced_ids = service.push_to_target(records)

        synced_count = len(synced_ids)
        failed_count = len(batch) - synced_count

        logger.info({
            "event": "sync.batch.success",
            "log_id": log_pk,
            "synced": synced_count,
            "failed": failed_count,
        })

        SyncRecordLog.objects.bulk_create(
            [
                SyncRecordLog(
                    sync_log=log,
                    record_id=rid,
                    status=SyncRecordLog.Status.SUCCESS,
                )
                for rid in batch
            ],
            ignore_conflicts=True,
        )

    # ✅ RETRYABLE → Celery retries automatically
    except RetryableSyncError as e:
        logger.warning({
            "event": "sync.batch.retry",
            "log_id": log_pk,
            "error": str(e),
            "retry": self.request.retries,
        })
        raise

    # ❌ NON-RETRYABLE → fail immediately
    except NonRetryableSyncError as e:
        logger.error({
            "event": "sync.batch.failed_permanent",
            "log_id": log_pk,
            "error": str(e),
        })

        SyncRecordLog.objects.bulk_create(
            [
                SyncRecordLog(
                    sync_log=log,
                    record_id=rid,
                    status=SyncRecordLog.Status.FAILED,
                    error=str(e),
                )
                for rid in batch
            ],
            ignore_conflicts=True,
        )

        synced_count = 0
        failed_count = len(batch)

    # fallback (unexpected)
    except Exception as e:
        logger.exception({
            "event": "sync.batch.unknown_error",
            "log_id": log_pk,
        })
        raise  # let Celery retry (safe fallback)

    # update counters
    SyncLog.objects.filter(pk=log.pk).update(
        records_synced=models.F("records_synced") + synced_count,
        records_failed=models.F("records_failed") + failed_count,
        completed_batches=models.F("completed_batches") + 1,
    )

    log.refresh_from_db()

    logger.info({
        "event": "sync.batch.end",
        "log_id": log_pk,
        "progress": f"{log.completed_batches}/{log.total_batches}",
    })

    _finalize_log(log, project)