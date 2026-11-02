"""Human corrections to an extraction, addressed by field path.

Paths: "document_number", "net_total", "supplier.vat_number", "lines[2].quantity", ... Any
string field of ExtractedDocument. The raw extraction is never modified; the corrected
version is rebuilt on demand by applying the stored corrections in order.
"""

import re
from collections.abc import Iterable
from typing import Any

from backend.app.extraction.schema import ExtractedDocument

_PATH = re.compile(r"^(?P<head>[a-z_0-9]+)(?:\[(?P<index>\d+)\])?(?:\.(?P<tail>[a-z_0-9]+))?$")


class InvalidFieldError(ValueError):
    pass


def _slot(data: dict[str, Any], path: str) -> tuple[dict[str, Any], str]:
    """The dict that holds the field, and the key within it."""
    match = _PATH.fullmatch(path)
    if not match:
        raise InvalidFieldError(f"not a field path: {path!r}")
    head, index, tail = match["head"], match["index"], match["tail"]
    if head not in data:
        raise InvalidFieldError(f"no field {head!r}")
    container: Any = data[head]
    if index is not None:
        if not isinstance(container, list) or int(index) >= len(container):
            raise InvalidFieldError(f"no item {index} in {head!r}")
        container = container[int(index)]
    if tail is None:
        if index is not None or not isinstance(container, str):
            raise InvalidFieldError(f"{path!r} is not a text field")
        return data, head
    if not isinstance(container, dict) or tail not in container:
        raise InvalidFieldError(f"no field {path!r}")
    if not isinstance(container[tail], str):
        raise InvalidFieldError(f"{path!r} is not a text field")
    return container, tail


def get_field(raw: ExtractedDocument, path: str) -> str:
    holder, key = _slot(raw.model_dump(mode="json"), path)
    value: str = holder[key]
    return value


def apply_corrections(
    raw: ExtractedDocument, corrections: Iterable[tuple[str, str]]
) -> ExtractedDocument:
    """A new ExtractedDocument with each (path, new value) applied in order."""
    data = raw.model_dump(mode="json")
    for path, value in corrections:
        holder, key = _slot(data, path)
        holder[key] = value
    try:
        return ExtractedDocument.model_validate(data)
    except ValueError as exc:  # e.g. an unknown doc_type
        raise InvalidFieldError(str(exc)) from exc
