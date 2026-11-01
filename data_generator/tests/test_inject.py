import random
from decimal import Decimal

import pytest

from backend.app.domain.document_set import DocumentSet
from backend.app.domain.errors import ErrorType
from data_generator.build import build_clean_set
from data_generator.inject import inject_error
from data_generator.plan import SetPlan
from data_generator.tests.helpers import (
    assert_invoice_consistent,
    changed_paths,
    flatten,
)

SEEDS = range(30)
TOTALS = {"net_total", "vat_total", "gross_total"}


def _clean(seed: int) -> DocumentSet:
    plan = SetPlan(index=1, template="classic", error_type=None, partial_delivery=seed % 2 == 0)
    return build_clean_set(seed, plan)


def _inject(seed: int, error_type: ErrorType) -> tuple[DocumentSet, DocumentSet]:
    clean = _clean(seed)
    return clean, inject_error(clean, error_type, random.Random(seed))


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("error_type", list(ErrorType))
def test_exactly_one_error_is_recorded(seed: int, error_type: ErrorType) -> None:
    clean, dirty = _inject(seed, error_type)
    assert clean.is_clean
    assert len(dirty.errors) == 1
    assert dirty.errors[0].type == error_type


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("error_type", list(ErrorType))
def test_po_and_dn_are_never_touched(seed: int, error_type: ErrorType) -> None:
    clean, dirty = _inject(seed, error_type)
    assert dirty.purchase_order == clean.purchase_order
    assert dirty.delivery_note == clean.delivery_note


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize(
    "error_type", [ErrorType.LINE_TOTAL_ERROR, ErrorType.VAT_ERROR, ErrorType.TOTAL_ERROR]
)
def test_arithmetic_errors_change_only_the_recorded_field(seed: int, error_type: ErrorType) -> None:
    clean, dirty = _inject(seed, error_type)
    error = dirty.errors[0]
    assert changed_paths(clean.invoices[0], dirty.invoices[0]) == {error.field}


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize(
    ("error_type", "changed_field"),
    [(ErrorType.QUANTITY_MISMATCH, "quantity"), (ErrorType.UNIT_PRICE_MISMATCH, "unit_price")],
)
def test_mismatch_errors_recompute_so_the_invoice_stays_consistent(
    seed: int, error_type: ErrorType, changed_field: str
) -> None:
    clean, dirty = _inject(seed, error_type)
    error = dirty.errors[0]
    assert error.field is not None
    line_path = error.field.removesuffix(f".{changed_field}")
    assert error.field.endswith(f".{changed_field}")

    assert_invoice_consistent(dirty.invoices[0])
    changed = changed_paths(clean.invoices[0], dirty.invoices[0])
    assert error.field in changed
    allowed = {error.field, f"{line_path}.line_net", f"{line_path}.line_vat"} | TOTALS
    assert changed <= allowed


@pytest.mark.parametrize("seed", SEEDS)
def test_quantity_mismatch_invoices_more_than_was_delivered(seed: int) -> None:
    _, dirty = _inject(seed, ErrorType.QUANTITY_MISMATCH)
    error = dirty.errors[0]
    assert error.expected is not None and error.actual is not None
    assert Decimal(error.actual) > Decimal(error.expected)
    delivered = {line.sku: line.quantity_delivered for line in dirty.delivery_note.lines}
    over = [line for line in dirty.invoices[0].lines if line.quantity > delivered[line.sku]]
    assert len(over) == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_unit_price_mismatch_differs_from_the_po_price(seed: int) -> None:
    _, dirty = _inject(seed, ErrorType.UNIT_PRICE_MISMATCH)
    po_price = {line.sku: line.unit_price for line in dirty.purchase_order.lines}
    off = [line for line in dirty.invoices[0].lines if line.unit_price != po_price[line.sku]]
    assert len(off) == 1


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize(
    "error_type", [ErrorType.LINE_TOTAL_ERROR, ErrorType.VAT_ERROR, ErrorType.TOTAL_ERROR]
)
def test_arithmetic_errors_are_too_large_to_be_a_rounding_difference(
    seed: int, error_type: ErrorType
) -> None:
    # A 1p error would be indistinguishable from a legitimate rounding method (ADR-0001).
    _, dirty = _inject(seed, error_type)
    error = dirty.errors[0]
    assert error.expected is not None and error.actual is not None
    assert abs(Decimal(error.actual) - Decimal(error.expected)) >= Decimal("0.50")


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("error_type", [t for t in ErrorType if t != ErrorType.DUPLICATE_INVOICE])
def test_recorded_values_match_the_documents(seed: int, error_type: ErrorType) -> None:
    clean, dirty = _inject(seed, error_type)
    error = dirty.errors[0]
    assert error.document_id == dirty.invoices[0].document_id
    assert error.field is not None
    assert flatten(dirty.invoices[0])[error.field] == error.actual
    assert error.expected != error.actual
    if error_type is ErrorType.QUANTITY_MISMATCH:
        dn_qty = {line.sku: line.quantity_delivered for line in clean.delivery_note.lines}
        line_index = int(error.field.split("[")[1].split("]")[0])
        sku = clean.invoices[0].lines[line_index].sku
        assert error.expected == str(dn_qty[sku])
    else:
        assert flatten(clean.invoices[0])[error.field] == error.expected


@pytest.mark.parametrize("seed", SEEDS)
def test_duplicate_invoice_is_an_exact_copy_with_a_new_id(seed: int) -> None:
    clean, dirty = _inject(seed, ErrorType.DUPLICATE_INVOICE)
    original, duplicate = dirty.invoices
    assert original == clean.invoices[0]
    assert duplicate.document_id != original.document_id
    assert changed_paths(original, duplicate) == {"document_id"}
    error = dirty.errors[0]
    assert error.document_id == duplicate.document_id
    assert error.related_document_id == original.document_id
    assert error.field is None
