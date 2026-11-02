"""Upload a generated dataset's PDFs as if a user had, for demos and manual testing.

    uv run --env-file .env python -m backend.app.pipeline.load_dataset \\
        --dataset data_generator/output/seed-42 --owner demo
    uv run --env-file .env python -m backend.app.worker --until-empty --cache-only

Only queues the files; the worker does the processing.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from backend.app.db.session import make_engine, make_session_factory
from backend.app.pipeline.process import ingest_file


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.app.pipeline.load_dataset")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--owner", default="demo")
    parser.add_argument(
        "--scans", action="store_true", help="upload the simulated scans instead of the PDFs"
    )
    args = parser.parse_args(argv)

    manifest = json.loads((args.dataset / "manifest.json").read_text())
    storage_root = Path(os.environ.get("STORAGE_DIR", "storage"))
    factory = make_session_factory(make_engine())
    queued = skipped = 0
    with factory() as session:
        for entry in manifest["sets"]:
            files = entry["scans"] if args.scans else entry["files"]
            for name in files.values():
                path = args.dataset / entry["set_id"] / name
                _, job = ingest_file(
                    session,
                    args.owner,
                    f"{entry['set_id']}/{name}",
                    path.read_bytes(),
                    storage_root,
                )
                queued += job is not None
                skipped += job is None
        session.commit()
    print(f"queued {queued} documents for owner {args.owner!r} ({skipped} already uploaded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
