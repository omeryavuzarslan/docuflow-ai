"""A job queue in a Postgres table (no Redis, no Celery).

- `claim` takes the oldest due job with SELECT ... FOR UPDATE SKIP LOCKED: a job locked by
  one worker is skipped by the others, so two workers never run the same job.
- `fail` puts the job back with a growing wait (10 s, 20 s, 40 s, ...) until `max_attempts`,
  then marks it failed and keeps the error.
- `requeue_stale` returns jobs whose worker died mid-way (locked too long) to the queue.

These functions change rows but do not commit; the caller decides the transaction, so a
claim and the work it starts can be committed (or rolled back) together.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.db.models import JobRow

BACKOFF_BASE = timedelta(seconds=10)
STALE_AFTER = timedelta(minutes=10)


def enqueue(
    session: Session,
    owner_id: str,
    kind: str,
    payload: dict[str, Any],
    run_after: datetime | None = None,
) -> JobRow:
    job = JobRow(owner_id=owner_id, kind=kind, payload=payload, status="queued")
    if run_after is not None:
        job.run_after = run_after
    session.add(job)
    return job


def claim(session: Session, worker_id: str, now: datetime) -> JobRow | None:
    job = session.scalars(
        select(JobRow)
        .where(JobRow.status == "queued", JobRow.run_after <= now)
        .order_by(JobRow.run_after, JobRow.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.locked_at = now
    job.locked_by = worker_id
    session.flush()
    return job


def complete(session: Session, job: JobRow) -> None:
    job.status = "done"
    job.locked_at = None
    job.locked_by = None
    session.flush()


def fail(session: Session, job: JobRow, error: str, now: datetime) -> None:
    job.last_error = error
    job.locked_at = None
    job.locked_by = None
    if job.attempts >= job.max_attempts:
        job.status = "failed"
    else:
        job.status = "queued"
        job.run_after = now + BACKOFF_BASE * 2 ** (job.attempts - 1)
    session.flush()


def requeue_stale(session: Session, now: datetime) -> int:
    """Put back jobs locked for longer than STALE_AFTER; returns how many."""
    result = session.execute(
        update(JobRow)
        .where(JobRow.status == "running", JobRow.locked_at < now - STALE_AFTER)
        .values(status="queued", locked_at=None, locked_by=None)
        .execution_options(synchronize_session="fetch")
    )
    session.flush()
    return int(result.rowcount)  # type: ignore[attr-defined]
