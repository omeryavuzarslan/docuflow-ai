"""Write the ground truth to disk.

    <out_dir>/seed-<seed>/
      manifest.json
      set-001/ground_truth.json
      ...

Byte-stable: key order follows the model field order, amounts are strings at fixed scale,
files are UTF-8 with "\n" line endings and a trailing newline.
"""

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backend.app.domain.document_set import DocumentSet

GENERATOR_VERSION = "1"


def write_dataset(
    sets: Sequence[DocumentSet], seed: int, out_dir: Path, force: bool = False
) -> Path:
    root = out_dir / f"seed-{seed}"
    if root.exists():
        if not force:
            raise FileExistsError(f"{root} already exists; pass --force to replace it")
        shutil.rmtree(root)
    root.mkdir(parents=True)

    for doc_set in sets:
        set_dir = root / doc_set.set_id
        set_dir.mkdir()
        _write_text(set_dir / "ground_truth.json", doc_set.model_dump_json(indent=2))

    _write_text(root / "manifest.json", json.dumps(_manifest(sets, seed), indent=2))
    return root


def _manifest(sets: Sequence[DocumentSet], seed: int) -> dict[str, Any]:
    return {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "sets": [
            {
                "set_id": doc_set.set_id,
                "template": doc_set.template,
                "clean": doc_set.is_clean,
                "errors": [error.type.value for error in doc_set.errors],
            }
            for doc_set in sets
        ],
    }


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
