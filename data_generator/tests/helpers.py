from typing import Any

from pydantic import BaseModel

from backend.app.domain.calculations import invoice_totals, line_net, line_vat
from backend.app.domain.document_set import DocumentSet
from backend.app.domain.documents import Invoice


def flatten(model: BaseModel) -> dict[str, Any]:
    """{"lines[0].quantity": "3.0000", "net_total": "70.22", ...} from a model's JSON form."""
    out: dict[str, Any] = {}

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, f"{path}[{i}]")
        else:
            out[path] = value

    walk(model.model_dump(mode="json"), "")
    return out


def changed_paths(before: BaseModel, after: BaseModel) -> set[str]:
    a, b = flatten(before), flatten(after)
    return {path for path in a.keys() | b.keys() if a.get(path) != b.get(path)}


def assert_invoice_consistent(invoice: Invoice) -> None:
    for line in invoice.lines:
        assert line.line_net == line_net(line.quantity, line.unit_price), line
        assert line.line_vat == line_vat(line.line_net, line.vat_rate), line
    totals = invoice_totals(invoice.lines)
    assert invoice.net_total == totals.net
    assert invoice.vat_total == totals.vat
    assert invoice.gross_total == totals.gross


def assert_set_consistent(doc_set: DocumentSet) -> None:
    """Everything a clean set must satisfy, internally and across PO -> DN -> invoice."""
    po, dn = doc_set.purchase_order, doc_set.delivery_note

    for po_line in po.lines:
        assert po_line.line_net == line_net(po_line.quantity, po_line.unit_price)
    assert po.net_total == sum(line.line_net for line in po.lines)

    assert dn.po_number == po.po_number
    assert dn.delivery_date >= po.issue_date
    po_by_sku = {line.sku: line for line in po.lines}
    dn_by_sku = {line.sku: line for line in dn.lines}
    assert dn_by_sku.keys() <= po_by_sku.keys()
    for sku, dn_line in dn_by_sku.items():
        assert dn_line.quantity_delivered <= po_by_sku[sku].quantity

    for invoice in doc_set.invoices:
        assert_invoice_consistent(invoice)
        assert invoice.po_number == po.po_number
        assert invoice.delivery_note_numbers == (dn.dn_number,)
        assert invoice.issue_date >= dn.delivery_date
        assert invoice.due_date > invoice.issue_date
        assert invoice.supplier == po.supplier == dn.supplier
        assert invoice.buyer == po.buyer == dn.buyer
        for inv_line in invoice.lines:
            assert inv_line.quantity == dn_by_sku[inv_line.sku].quantity_delivered
            assert inv_line.unit_price == po_by_sku[inv_line.sku].unit_price
