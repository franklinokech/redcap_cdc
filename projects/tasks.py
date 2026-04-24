import math
import logging

from celery import shared_task
from django.utils import timezone
from django.db import models

from projects.models import RedcapProject, SyncLog, SyncRecordLog
from projects.services.sync_service import SyncService

logger = logging.getLogger("projects")


# =========================================================
# EVENT LOGGER HELPERS
# =========================================================

def log_event(event: str, **data):
    """
    Central structured logger.
    Ensures consistent schema across all sync events.
    """
    logger.info(
        {
            "event": event,
            "timestamp": timezone.now().isoformat(),
            **data,
        }
    )


def _chunk_size(project):
    return max(project.chunk_size or 100, 1)


def _finalize_log(log: SyncLog, project: RedcapProject):
    if log.ended_at is not None:
        return

    log.refresh_from_db()

    if 0 < log.total_batches <= log.completed_batches:

        log_event(
            "sync.batch.finalize",
            log_id=log.pk,
            synced=log.records_synced,
            failed=log.records_failed,
        )

        log.status = (
            SyncLog.SyncStatus.SUCCESS
            if log.records_failed == 0
            else SyncLog.SyncStatus.FAILED
        )

        log.ended_at = timezone.now()
        log.save(update_fields=["status", "ended_at"])

        project.last_sync_timestamp = log.ended_at
        project.save(update_fields=["last_sync_timestamp"])


# =========================================================
# FULL SYNC
# =========================================================

@shared_task
def run_full_sync_task(project_id):
    project = RedcapProject.objects.get(pk=project_id)
    service = SyncService(project)

    log_event("sync.full.start", project_id=project_id)

    log = service._start_log()
    log.status = SyncLog.SyncStatus.RUNNING
    log.save(update_fields=["status"])

    record_ids = service.fetch_all_record_ids()
    chunk_size = _chunk_size(project)

    log.records_expected = len(record_ids)
    log.total_batches = math.ceil(len(record_ids) / chunk_size)
    log.completed_batches = 0
    log.save()

    log_event(
        "sync.full.state",
        log_id=log.pk,
        records=len(record_ids),
        chunk_size=chunk_size,
        total_batches=log.total_batches,
    )

    for i, batch in enumerate(service._chunk(record_ids), start=1):
        log_event(
            "sync.batch.queue",
            sync_type="full",
            log_id=log.pk,
            batch=i,
            size=len(batch),
        )
        process_batch_task.delay(log.pk, batch)

    log_event("sync.full.end", log_id=log.pk)

    return log.pk


# =========================================================
# INCREMENTAL SYNC
# =========================================================

@shared_task
def run_incremental_sync_task(project_id):
    project = RedcapProject.objects.get(pk=project_id)
    service = SyncService(project)

    log_event("sync.incremental.start", project_id=project_id)

    log = service._start_log()
    log.status = SyncLog.SyncStatus.RUNNING
    log.save(update_fields=["status"])

    begin_time = project.last_sync_timestamp

    log_event(
        "sync.incremental.state",
        project_id=project_id,
        last_sync_ts=begin_time.isoformat() if begin_time else None,
    )

    logs = service.fetch_logs(begin_time)
    record_ids = service.extract_changed_records(logs)

    log_event(
        "sync.incremental.changes",
        project_id=project_id,
        changed_records=len(record_ids),
    )

    chunk_size = _chunk_size(project)

    # No changes
    if not record_ids:
        now = timezone.now()

        log.records_expected = 0
        log.total_batches = 0
        log.completed_batches = 0
        log.status = SyncLog.SyncStatus.SUCCESS
        log.ended_at = now
        log.save()

        project.last_sync_timestamp = now
        project.save(update_fields=["last_sync_timestamp"])

        log_event(
            "sync.incremental.end",
            log_id=log.pk,
            status="no_changes",
        )

        return log.pk

    log.records_expected = len(record_ids)
    log.total_batches = math.ceil(len(record_ids) / chunk_size)
    log.completed_batches = 0
    log.save()

    for i, batch in enumerate(service._chunk(record_ids), start=1):
        log_event(
            "sync.batch.queue",
            sync_type="incremental",
            log_id=log.pk,
            batch=i,
            size=len(batch),
        )
        process_batch_task.delay(log.pk, batch)

    log_event(
        "sync.incremental.end",
        log_id=log.pk,
        status="queued",
    )

    return log.pk


# =========================================================
# BATCH PROCESSING
# =========================================================

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_batch_task(self, log_pk, batch):
    log = SyncLog.objects.get(pk=log_pk)
    project = log.project
    service = SyncService(project)

    log_event(
        "sync.batch.start",
        log_id=log_pk,
        task_id=self.request.id,
        size=len(batch),
    )

    try:
        records = service.fetch_records_by_ids(batch)
        synced_ids = service.push_to_target(records)

        log_event(
            "sync.batch.synced",
            log_id=log_pk,
            fetched=len(records),
            synced=len(synced_ids),
        )

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

        synced_count = len(synced_ids)
        failed_count = len(batch) - synced_count

    except Exception as e:
        log_event(
            "sync.batch.error",
            log_id=log_pk,
            error=str(e),
        )

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

    SyncLog.objects.filter(pk=log.pk).update(
        records_synced=models.F("records_synced") + synced_count,
        records_failed=models.F("records_failed") + failed_count,
        completed_batches=models.F("completed_batches") + 1,
    )

    log.refresh_from_db()

    log_event(
        "sync.batch.end",
        log_id=log_pk,
        progress=f"{log.completed_batches}/{log.total_batches}",
    )

    _finalize_log(log, project)