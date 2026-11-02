"""Where uploaded files live. Local disk for now (`storage/`, gitignored); swapping in cloud
blob storage later only changes this module."""

import hashlib
from pathlib import Path


def save_file(root: Path, owner_id: str, data: bytes) -> tuple[str, Path]:
    """Store bytes under their content hash; returns (sha256, path). Saving the same bytes
    twice is harmless: same name, same content."""
    sha = hashlib.sha256(data).hexdigest()
    path = root / owner_id / f"{sha}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    return sha, path
