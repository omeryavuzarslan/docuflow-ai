from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from backend.app.db.models import JobRow
from backend.app.jobs.queue import STALE_AFTER, claim, complete, enqueue, fail, requeue_stale

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _job(session: Session, run_after: datetime = NOW - timedelta(seconds=1)) -> JobRow:
    job = enqueue(
        session,
        owner_id="o",
        kind="process_document",
        payload={"document_id": "d"},
        run_after=run_after,
    )
    session.flush()
    return job


def test_claim_takes_the_oldest_due_job_and_marks_it_running(session: Session) -> None:
    first = _job(session, NOW - timedelta(minutes=2))
    _job(session, NOW - timedelta(minutes=1))
    _job(session, NOW + timedelta(minutes=5))  # not due yet

    job = claim(session, worker_id="w1", now=NOW)

    assert job is not None and job.id == first.id
    assert (job.status, job.attempts, job.locked_by) == ("running", 1, "w1")


def test_nothing_to_claim(session: Session) -> None:
    _job(session, NOW + timedelta(minutes=5))
    assert claim(session, worker_id="w1", now=NOW) is None


def test_two_workers_never_get_the_same_job(engine: Engine) -> None:
    # Real separate connections, so this needs real commits; cleaned up at the end.
    with Session(engine) as setup:
        job = enqueue(
            setup, owner_id="queue-test", kind="k", payload={}, run_after=NOW - timedelta(seconds=1)
        )
        setup.commit()
        job_id = job.id
    try:
        with Session(engine) as a, Session(engine) as b:
            got_a = claim(a, worker_id="a", now=NOW)  # holds the row lock until commit
            got_b = claim(b, worker_id="b", now=NOW)  # SKIP LOCKED: passes over it
            assert got_a is not None and got_a.id == job_id
            assert got_b is None or got_b.id != job_id
            a.rollback()
            b.rollback()
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(JobRow).where(JobRow.owner_id == "queue-test"))
            cleanup.commit()


def test_failed_job_is_retried_later_with_growing_waits_then_given_up(session: Session) -> None:
    job = _job(session)
    waits: list[timedelta] = []
    for _ in range(job.max_attempts):
        claimed = claim(session, worker_id="w", now=NOW + timedelta(hours=len(waits)))
        assert claimed is not None
        fail(session, claimed, "boom", now=NOW + timedelta(hours=len(waits)))
        if claimed.status == "queued":
            waits.append(claimed.run_after - (NOW + timedelta(hours=len(waits))))
    assert waits == [timedelta(seconds=10), timedelta(seconds=20)]
    assert (job.status, job.attempts, job.last_error) == ("failed", 3, "boom")


def test_completed_job_is_done(session: Session) -> None:
    job = _job(session)
    claimed = claim(session, worker_id="w", now=NOW)
    assert claimed is not None
    complete(session, claimed)
    assert (job.status, job.locked_by) == ("done", None)


def test_jobs_of_a_crashed_worker_go_back_to_the_queue(session: Session) -> None:
    job = _job(session)
    claim(session, worker_id="crashed", now=NOW)
    assert requeue_stale(session, now=NOW + STALE_AFTER / 2) == 0
    assert requeue_stale(session, now=NOW + STALE_AFTER + timedelta(seconds=1)) == 1
    assert (job.status, job.locked_by) == ("queued", None)
    again = claim(session, worker_id="w2", now=NOW + STALE_AFTER + timedelta(seconds=2))
    assert again is not None and again.attempts == 2
