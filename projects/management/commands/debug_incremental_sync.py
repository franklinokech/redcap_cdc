import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from projects.models import RedcapProject, SyncRecordLog
from projects.services.sync_service import SyncService


class Command(BaseCommand):
    help = "Debug incremental sync with full tracing"

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--limit-batches", type=int, default=10)
        parser.add_argument("--lookback-minutes", type=int, default=60)

    def handle(self, *args, **options):
        project_id = options["project_id"]
        limit_batches = options["limit_batches"]
        lookback = options["lookback_minutes"]

        project = RedcapProject.objects.get(id=project_id)
        service = SyncService(project)

        self.stdout.write(self.style.SUCCESS("\n🚀 STARTING INCREMENTAL SYNC DEBUG"))
        self.stdout.write(f"Project: {project.name}")
        self.stdout.write(f"Chunk size: {project.chunk_size}")
        self.stdout.write(f"Current last_sync_timestamp: {project.last_sync_timestamp}")
        self.stdout.write("=" * 60)

        log = service._start_log()

        try:
            start_time = time.time()

            # -----------------------------
            # STEP 1: FETCH LOGS
            # -----------------------------
            self.stdout.write("\n📥 Fetching REDCap logs...")

            # Use project's last_sync_timestamp if available, otherwise use lookback
            if project.last_sync_timestamp:
                begin_time = project.last_sync_timestamp - timezone.timedelta(minutes=1)
                self.stdout.write(f"Using last_sync_timestamp: {project.last_sync_timestamp}")
                self.stdout.write(f"Begin time (with 1min overlap): {begin_time}")
            else:
                begin_time = timezone.now() - timezone.timedelta(minutes=lookback)
                self.stdout.write(f"No previous sync, using lookback: {lookback} minutes")
                self.stdout.write(f"Begin time: {begin_time}")

            logs = service.fetch_logs(begin_time)

            self.stdout.write(f"Logs fetched: {len(logs)}")

            record_ids = service.extract_changed_records(logs)

            self.stdout.write(self.style.SUCCESS(
                f"🧠 Changed records detected: {len(record_ids)}"
            ))

            log.records_expected = len(record_ids)
            log.save()

            if not record_ids:
                self.stdout.write(self.style.WARNING("No changes detected"))
                # Still need to finalize to update timestamp
                log = service._finalize_sync(log)
                self.stdout.write(f"✅ Updated last_sync_timestamp to: {project.last_sync_timestamp}")
                return

            # -----------------------------
            # STEP 2: CREATE RECORD LOGS
            # -----------------------------
            record_log_map = {}

            for rid in record_ids:
                record_log_map[rid] = SyncRecordLog.objects.create(
                    sync_log=log,
                    record_id=rid,
                    status=SyncRecordLog.Status.PENDING
                )

            # -----------------------------
            # STEP 3: PROCESS BATCHES
            # -----------------------------
            total_synced = 0
            total_failed = 0
            batch_count = 0

            for batch in service._chunk(record_ids):

                batch_count += 1

                self.stdout.write(f"\n🔹 Batch {batch_count}")
                self.stdout.write(f"Size: {len(batch)}")
                self.stdout.write(f"IDs sample: {batch[:5]}")

                try:
                    t0 = time.time()

                    records = service.fetch_records_by_ids(batch)

                    self.stdout.write(f"   📦 fetched: {len(records)}")

                    synced_ids = service.push_to_target(records)

                    duration = time.time() - t0

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"   🚀 synced: {len(synced_ids)}"
                        )
                    )
                    self.stdout.write(f"   ⏱ time: {duration:.2f}s")

                    total_synced += len(synced_ids)

                    for rid in batch:
                        rec_log = record_log_map.get(rid)
                        if rec_log:
                            rec_log.status = SyncRecordLog.Status.SUCCESS
                            rec_log.save()

                except Exception as e:
                    duration = time.time() - t0

                    self.stdout.write(self.style.ERROR("   ❌ BATCH FAILED"))
                    self.stdout.write(f"   ⏱ time: {duration:.2f}s")
                    self.stdout.write(f"   error: {str(e)[:300]}")

                    total_failed += len(batch)

                    for rid in batch:
                        rec_log = record_log_map.get(rid)
                        if rec_log:
                            rec_log.status = SyncRecordLog.Status.FAILED
                            rec_log.error = str(e)[:1000]
                            rec_log.save()

                if batch_count >= limit_batches:
                    self.stdout.write("\n🛑 DEBUG LIMIT REACHED")
                    break

            # -----------------------------
            # FINAL SUMMARY - USING SERVICE METHOD
            # -----------------------------
            duration_total = time.time() - start_time

            # Update log counts
            log.records_synced = total_synced
            log.records_failed = total_failed
            log.save()

            # Use service's _finalize_sync to properly finish
            # This sets log.ended_at, log.status, AND updates project.last_sync_timestamp
            log = service._finalize_sync(log)

            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.SUCCESS("📊 INCREMENTAL SYNC SUMMARY"))
            self.stdout.write(f"Expected: {log.records_expected}")
            self.stdout.write(f"Synced: {log.records_synced}")
            self.stdout.write(f"Failed: {log.records_failed}")
            self.stdout.write(f"Started at: {log.started_at}")
            self.stdout.write(f"Ended at: {log.ended_at}")
            self.stdout.write(f"Project last_sync_timestamp: {project.last_sync_timestamp}")
            self.stdout.write(f"Duration: {duration_total:.2f}s")
            self.stdout.write("=" * 60)

            # Verify timestamp was updated
            if project.last_sync_timestamp == log.ended_at:
                self.stdout.write(self.style.SUCCESS("✅ last_sync_timestamp successfully updated!"))
            else:
                self.stdout.write(self.style.ERROR("❌ last_sync_timestamp was NOT updated correctly"))

        except Exception as e:
            # On fatal error, try to finalize properly
            log.details = str(e)
            log = service._finish_log(log, success=False, error=str(e))

            # Optionally update timestamp even on failure?
            # project.last_sync_timestamp = log.ended_at
            # project.save(update_fields=["last_sync_timestamp"])

            self.stdout.write(self.style.ERROR("\n❌ FATAL ERROR"))
            self.stdout.write(str(e))
            self.stdout.write(f"Log status: {log.status}")
            self.stdout.write(f"Log ended_at: {log.ended_at}")