import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from projects.models import RedcapProject, SyncRecordLog
from projects.services.sync_service import SyncService


class Command(BaseCommand):
    help = "Debug full sync with step-by-step tracing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--project-id",
            type=int,
            help="Project ID to run sync for",
        )
        parser.add_argument(
            "--limit-batches",
            type=int,
            default=10,
            help="Limit number of batches for debugging",
        )

    def handle(self, *args, **options):
        project_id = options.get("project_id")
        limit_batches = options.get("limit_batches")

        project = RedcapProject.objects.get(id=project_id)
        service = SyncService(project)

        self.stdout.write(self.style.SUCCESS("\n🚀 STARTING FULL SYNC DEBUG"))
        self.stdout.write(f"Project: {project.name}")
        self.stdout.write(f"Chunk size: {project.chunk_size}")
        self.stdout.write("=" * 60)

        log = service._start_log()

        try:
            start_time = time.time()

            # -----------------------------
            # STEP 1: FETCH IDS
            # -----------------------------
            self.stdout.write("\n📥 Fetching record IDs...")

            record_ids = service.fetch_all_record_ids()

            self.stdout.write(self.style.SUCCESS(f"✅ Total records: {len(record_ids)}"))

            log.records_expected = len(record_ids)
            log.save()

            # -----------------------------
            # STEP 2: PROCESS BATCHES
            # -----------------------------
            total_synced = 0
            total_failed = 0
            batch_count = 0

            for batch in service._chunk(record_ids):

                batch_count += 1

                self.stdout.write(f"\n🔹 Batch {batch_count} | size={len(batch)}")
                self.stdout.write(f"IDs sample: {batch[:5]}")

                try:
                    t0 = time.time()

                    records = service.fetch_records_by_ids(batch)

                    self.stdout.write(f"   📦 fetched: {len(records)}")

                    synced_ids = service.push_to_target(records)

                    duration = time.time() - t0

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"   🚀 pushed: {len(synced_ids)} records"
                        )
                    )
                    self.stdout.write(f"   ⏱ batch time: {duration:.2f}s")

                    total_synced += len(synced_ids)

                    for rid in batch:
                        SyncRecordLog.objects.update_or_create(
                            sync_log=log,
                            record_id=rid,
                            defaults={"status": "SUCCESS"}
                        )

                except Exception as e:
                    duration = time.time() - t0

                    self.stdout.write(self.style.ERROR("   ❌ FAILED batch"))
                    self.stdout.write(f"   ⏱ failed after: {duration:.2f}s")
                    self.stdout.write(f"   error: {str(e)[:300]}")

                    total_failed += len(batch)

                    for rid in batch:
                        SyncRecordLog.objects.update_or_create(
                            sync_log=log,
                            record_id=rid,
                            defaults={
                                "status": "FAILED",
                                "error": str(e)[:1000],
                            }
                        )

                # stop early for debugging
                if batch_count >= limit_batches:
                    self.stdout.write("\n🛑 DEBUG LIMIT REACHED")
                    break

            # -----------------------------
            # FINAL SUMMARY
            # -----------------------------
            duration_total = time.time() - start_time

            log.records_synced = total_synced
            log.records_failed = total_failed
            log.ended_at = timezone.now()
            log.status = "SUCCESS" if total_failed == 0 else "FAILED"
            log.save()

            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.SUCCESS("📊 FULL SYNC SUMMARY"))
            self.stdout.write(f"Expected: {log.records_expected}")
            self.stdout.write(f"Synced: {total_synced}")
            self.stdout.write(f"Failed: {total_failed}")
            self.stdout.write(f"Time: {duration_total:.2f}s")
            self.stdout.write("=" * 60)

        except Exception as e:
            log.status = "FAILED"
            log.details = str(e)
            log.save()

            self.stdout.write(self.style.ERROR("\n❌ FATAL ERROR"))
            self.stdout.write(str(e))