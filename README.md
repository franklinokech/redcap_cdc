# REDCap Sync System

A distributed, fault-tolerant data synchronization system built with
Django + Celery.

------------------------------------------------------------------------

## Overview

This system synchronizes data between a REDCap source and target
using: - Batch processing - Celery workers - Retry-aware execution -
Structured logging - Database audit trails

------------------------------------------------------------------------

## Architecture

REDCap Source → SyncService → Celery Tasks → REDCap Target → SyncLog
DB + Logs

------------------------------------------------------------------------

## Sync Modes

### Full Sync

-   Syncs all records

### Incremental Sync

-   Syncs only changed records using REDCap logs

------------------------------------------------------------------------

## Retry Strategy

### Retryable

-   Network errors
-   Timeout
-   5xx responses

### Non-Retryable

-   400 validation errors
-   Bad payloads
-   Auth errors

------------------------------------------------------------------------

## Logging Events

-   sync.incremental.start
-   sync.incremental.state
-   sync.incremental.changes
-   sync.incremental.end
-   sync.batch.start
-   sync.batch.end
-   sync.batch.failed_permanent

------------------------------------------------------------------------

## TODO

### Data Quality
- Schema ingestion
- Validation engine
- Record checker
- Django integration

### High Priority

-   Structured error schema storage
-   Retry dashboard metrics
-   Dead-letter queue

### Medium Priority

-   Partial success handling
-   Sync pause/resume
-   Performance tuning

------------------------------------------------------------------------

## Future

-   DAG orchestration (Dagster)
-   Event-driven sync
-   Multi-region sync

------------------------------------------------------------------------

## Status

Core system is stable and production-ready for batch sync operations.
