"""Labelled errors injected by the data generator: the answer key for evaluation."""

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from backend.app.domain.types import DomainModel


class ErrorType(StrEnum):
    QUANTITY_MISMATCH = "quantity_mismatch"
    UNIT_PRICE_MISMATCH = "unit_price_mismatch"
    LINE_TOTAL_ERROR = "line_total_error"
    VAT_ERROR = "vat_error"
    TOTAL_ERROR = "total_error"
    DUPLICATE_INVOICE = "duplicate_invoice"


SET_LEVEL_ERRORS = frozenset({ErrorType.DUPLICATE_INVOICE})


class InjectedError(DomainModel):
    """One injected error.

    `field` is a path inside the document, e.g. "lines[1].quantity" or "vat_total".
    Set-level errors (duplicate invoice) are about a whole document, so `field` is None
    and `related_document_id` points at the original. `expected` and `actual` are strings
    so Decimals keep their exact digits in JSON.
    """

    type: ErrorType
    document_id: str
    field: str | None
    expected: str | None = None
    actual: str | None = None
    related_document_id: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if self.type in SET_LEVEL_ERRORS:
            if self.field is not None:
                raise ValueError(f"{self.type} is a set-level error: field must be None")
            if self.related_document_id is None:
                raise ValueError(f"{self.type} needs related_document_id")
        elif self.field is None:
            raise ValueError(f"{self.type} is a field-level error: field is required")
        return self
