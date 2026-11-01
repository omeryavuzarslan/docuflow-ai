from typing import Self

from pydantic import Field, model_validator

from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder
from backend.app.domain.errors import InjectedError
from backend.app.domain.types import DomainModel


class DocumentSet(DomainModel):
    """One PO -> DN -> invoice(s) set plus its injected errors.

    This is the ground truth: one JSON file per set. There can be several invoices
    because a duplicate invoice is one of the injected errors.
    """

    set_id: str
    template: str
    purchase_order: PurchaseOrder
    delivery_note: DeliveryNote
    invoices: tuple[Invoice, ...] = Field(min_length=1)
    errors: tuple[InjectedError, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not self.errors

    @property
    def document_ids(self) -> list[str]:
        return [
            self.purchase_order.document_id,
            self.delivery_note.document_id,
            *(invoice.document_id for invoice in self.invoices),
        ]

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        ids = self.document_ids
        if len(ids) != len(set(ids)):
            raise ValueError(f"document ids must be unique within a set: {ids}")
        known = set(ids)
        for error in self.errors:
            for ref in (error.document_id, error.related_document_id):
                if ref is not None and ref not in known:
                    raise ValueError(f"error refers to unknown document {ref!r}")
        return self
