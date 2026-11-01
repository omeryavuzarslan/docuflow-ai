"""Write the ground truth to disk.

    <out_dir>/seed-<seed>/
      manifest.json
      set-001/ground_truth.json
      set-001/po.pdf, dn.pdf, inv-1.pdf                  (unless render_pdfs=False)
      set-001/po.scan.pdf, dn.scan.pdf, inv-1.scan.pdf   simulated scans of the same
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
from data_generator.render import write_pdfs
from data_generator.scan import make_scan

GENERATOR_VERSION = "1"


def write_dataset(
    sets: Sequence[DocumentSet],
    seed: int,
    out_dir: Path,
    force: bool = False,
    render_pdfs: bool = True,
) -> Path:
    root = out_dir / f"seed-{seed}"
    if root.exists():
        if not force:
            raise FileExistsError(f"{root} already exists; pass --force to replace it")
        shutil.rmtree(root)
    root.mkdir(parents=True)

    files: dict[str, dict[str, str]] = {}
    scans: dict[str, dict[str, str]] = {}
    for doc_set in sets:
        set_dir = root / doc_set.set_id
        set_dir.mkdir()
        _write_text(set_dir / "ground_truth.json", doc_set.model_dump_json(indent=2))
        if render_pdfs:
            files[doc_set.set_id] = write_pdfs(doc_set, set_dir)
            scans[doc_set.set_id] = _write_scans(files[doc_set.set_id], set_dir, seed)

    manifest = _manifest(sets, seed, files, scans)
    _write_text(root / "manifest.json", json.dumps(manifest, indent=2))
    return root


def _write_scans(files: dict[str, str], set_dir: Path, seed: int) -> dict[str, str]:
    scans = {}
    for document_id, name in files.items():
        scan_name = name.removesuffix(".pdf") + ".scan.pdf"
        pdf = (set_dir / name).read_bytes()
        (set_dir / scan_name).write_bytes(make_scan(pdf, f"{seed}:{document_id}:scan"))
        scans[document_id] = scan_name
    return scans


def _manifest(
    sets: Sequence[DocumentSet],
    seed: int,
    files: dict[str, dict[str, str]],
    scans: dict[str, dict[str, str]],
) -> dict[str, Any]:
    return {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "sets": [
            {
                "set_id": doc_set.set_id,
                "template": doc_set.template,
                "clean": doc_set.is_clean,
                "errors": [error.type.value for error in doc_set.errors],
                # document_id -> PDF file name: links each PDF to its ground truth.
                "files": files.get(doc_set.set_id, {}),
                "scans": scans.get(doc_set.set_id, {}),
            }
            for doc_set in sets
        ],
    }


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
