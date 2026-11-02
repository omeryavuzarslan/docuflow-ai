"""The background worker: takes jobs from the queue and runs them.

    uv run --env-file .env python -m backend.app.worker            # run until stopped
    uv run --env-file .env python -m backend.app.worker --until-empty
    uv run --env-file .env python -m backend.app.worker --cache-only  # never call the API

Each job runs in its own transaction: if processing raises, everything it wrote is rolled
back and the job is retried later (see jobs/queue.py). Ctrl+C finishes the current job
first, then stops.
"""

import argparse
import logging
import os
import signal
import socket
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType

from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.models import DocumentRow, JobRow
from backend.app.db.session import make_engine, make_session_factory
from backend.app.jobs.queue import claim, complete, fail, requeue_stale
from backend.app.llm.client import CacheOnlyClient, LLMClient
from backend.app.pipeline.process import PROCESS_DOCUMENT, Services, process_document

log = logging.getLogger("worker")

DEFAULT_MODEL = "claude-haiku-5-5"
IDLE_SLEEP_SECONDS = 2.0


def handle(session: Session, job: JobRow, services: Services) -> None:
    if job.kind == PROCESS_DOCUMENT:
        process_document(session, job.payload["document_id"], job.owner_id, services)
    else:
        raise ValueError(f"unknown job kind {job.kind!r}")


def run_once(factory: sessionmaker[Session], services: Services, worker_id: str) -> bool:
    """Claim and run one job. Returns False when there was nothing to do."""
    now = datetime.now(UTC)
    with factory() as session:
        requeue_stale(session, now)
        job = claim(session, worker_id, now)
        session.commit()  # the claim is visible (and the row unlocked) from here on
        if job is None:
            return False
        job_id = job.id

    try:
        with factory() as session:
            job = session.get(JobRow, job_id)
            assert job is not None
            handle(session, job, services)
            complete(session, job)
            session.commit()
            log.info("job %s done (%s)", job_id, job.kind)
    except Exception as exc:  # any failure: record it and let the queue retry
        log.exception("job %s failed", job_id)
        with factory() as session:
            job = session.get(JobRow, job_id)
            assert job is not None
            fail(session, job, f"{type(exc).__name__}: {exc}", datetime.now(UTC))
            if job.status == "failed" and job.kind == PROCESS_DOCUMENT:
                document = session.get(DocumentRow, job.payload["document_id"])
                if document is not None:
                    document.status = "failed"
            session.commit()
    return True


def run_until_empty(factory: sessionmaker[Session], services: Services, worker_id: str) -> int:
    """Process jobs until none is due; returns how many were run."""
    count = 0
    while run_once(factory, services, worker_id):
        count += 1
    return count


def _services(cache_only: bool) -> Services:
    from backend.app.ingestion.parse import parse_pdf

    llm = LLMClient(
        cache_dir=Path(os.environ.get("LLM_CACHE_DIR", ".cache/llm")),
        anthropic_client=CacheOnlyClient() if cache_only else None,
    )
    return Services(
        parse=parse_pdf,
        llm=llm,
        model=os.environ.get("EXTRACTION_MODEL", DEFAULT_MODEL),
        storage_root=Path(os.environ.get("STORAGE_DIR", "storage")),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.app.worker")
    parser.add_argument("--until-empty", action="store_true", help="stop when the queue is empty")
    parser.add_argument("--cache-only", action="store_true", help="use cached LLM answers only")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    factory = make_session_factory(make_engine())
    services = _services(args.cache_only)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"

    if args.until_empty:
        log.info("processed %d jobs", run_until_empty(factory, services, worker_id))
        return 0

    stopping = False

    def stop(signum: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        log.info("signal %d: finishing the current job, then stopping", signum)
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    log.info("worker %s started", worker_id)
    while not stopping:
        if not run_once(factory, services, worker_id):
            time.sleep(IDLE_SLEEP_SECONDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
