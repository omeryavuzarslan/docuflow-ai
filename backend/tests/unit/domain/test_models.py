from datetime import date
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from backend.app.domain.document_set import DocumentSet
from backend.app.domain.documents import Invoice, InvoiceLine
from backend.app.domain.errors import ErrorType, InjectedError
from backend.app.domain.types import Money, Quantity, UnitPrice
from backend.tests.unit.domain.factories import (
    make_document_set,
    make_duplicate_error,
    make_invoice,
    make_invoice_lines,
)

D = Decimal


class _Amounts(BaseModel):
    money: Money = D("0")
    unit_price: UnitPrice = D("0")
    quantity: Quantity = D("1")


# --- numeric types -------------------------------------------------------------------


@pytest.mark.parametrize("field", ["money", "unit_price", "quantity"])
def test_numeric_types_reject_float(field: str) -> None:
    with pytest.raises(ValidationError, match="float"):
        _Amounts.model_validate({field: 19.99})


def test_numeric_types_reject_float_from_json() -> None:
    with pytest.raises(ValidationError, match="float"):
        _Amounts.model_validate_json('{"money": 19.99}')


def test_numeric_types_accept_decimal_str_and_int() -> None:
    a = _Amounts.model_validate({"money": D("1.50"), "unit_price": "2.5", "quantity": 3})
    assert a.money == D("1.50")
    assert a.unit_price == D("2.5")
    assert a.quantity == D("3")


def test_money_rejects_more_than_two_decimal_places() -> None:
    with pytest.raises(ValidationError):
        _Amounts(money=D("1.234"))


def test_unit_price_and_quantity_allow_four_decimal_places_only() -> None:
    _Amounts(unit_price=D("1.2345"), quantity=D("0.0001"))
    with pytest.raises(ValidationError):
        _Amounts(unit_price=D("1.23456"))
    with pytest.raises(ValidationError):
        _Amounts(quantity=D("1.23456"))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_money_rejects_non_finite(value: str) -> None:
    with pytest.raises(ValidationError):
        _Amounts.model_validate({"money": value})


def test_values_are_stored_at_database_scale() -> None:
    # Same value, one representation: keeps the JSON output byte-stable.
    a = _Amounts.model_validate({"money": "1E+2", "unit_price": "19.99", "quantity": "3"})
    assert str(a.money) == "100.00"
    assert str(a.unit_price) == "19.9900"
    assert str(a.quantity) == "3.0000"


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _Amounts(quantity=D("0"))


# --- model behaviour -----------------------------------------------------------------


def test_models_are_frozen() -> None:
    invoice = make_invoice()
    with pytest.raises(ValidationError):
        invoice.net_total = D("1.00")  # type: ignore[misc]


def test_model_copy_leaves_original_untouched() -> None:
    invoice = make_invoice()
    changed = invoice.model_copy(update={"net_total": D("1.00")})
    assert changed.net_total == D("1.00")
    assert invoice.net_total == D("70.22")


def test_unknown_fields_are_rejected() -> None:
    data = make_invoice_lines()[0].model_dump()
    data["discount"] = "5.00"
    with pytest.raises(ValidationError, match="discount"):
        InvoiceLine.model_validate(data)


def test_invoice_needs_at_least_one_line() -> None:
    with pytest.raises(ValidationError):
        Invoice.model_validate({**make_invoice().model_dump(), "lines": ()})


def test_documents_carry_their_type() -> None:
    doc_set = make_document_set()
    assert doc_set.purchase_order.doc_type == "purchase_order"
    assert doc_set.delivery_note.doc_type == "delivery_note"
    assert doc_set.invoices[0].doc_type == "invoice"


# --- JSON round trip -----------------------------------------------------------------


def test_document_set_json_round_trip() -> None:
    doc_set = make_document_set()
    restored = DocumentSet.model_validate_json(doc_set.model_dump_json())
    assert restored == doc_set


def test_json_writes_amounts_as_strings_and_dates_as_iso() -> None:
    data = make_invoice().model_dump(mode="json")
    assert data["gross_total"] == "84.26"
    assert data["lines"][0]["unit_price"] == "19.9900"
    assert data["issue_date"] == "2026-10-06"


# --- injected errors -----------------------------------------------------------------


def test_field_level_error_requires_field() -> None:
    with pytest.raises(ValidationError, match="field"):
        InjectedError(
            type=ErrorType.QUANTITY_MISMATCH,
            document_id="set001-inv-1",
            field=None,
            expected="3",
            actual="5",
        )


def test_duplicate_invoice_error_has_no_field_but_needs_related_document() -> None:
    error = make_duplicate_error()
    assert error.field is None
    with pytest.raises(ValidationError, match="related_document_id"):
        InjectedError(type=ErrorType.DUPLICATE_INVOICE, document_id="set001-inv-2", field=None)
    with pytest.raises(ValidationError, match="field"):
        InjectedError(
            type=ErrorType.DUPLICATE_INVOICE,
            document_id="set001-inv-2",
            field="invoice_number",
            related_document_id="set001-inv-1",
        )


# --- document set --------------------------------------------------------------------


def test_clean_set() -> None:
    assert make_document_set().is_clean


def test_set_with_duplicate_invoice() -> None:
    duplicate = make_invoice(document_id="set001-inv-2")
    doc_set = make_document_set(
        invoices=(make_invoice(), duplicate), errors=(make_duplicate_error(),)
    )
    assert not doc_set.is_clean
    assert doc_set.invoices[0].invoice_number == doc_set.invoices[1].invoice_number


def test_set_rejects_error_for_unknown_document() -> None:
    error = InjectedError(
        type=ErrorType.VAT_ERROR,
        document_id="no-such-doc",
        field="vat_total",
        expected="14.04",
        actual="15.04",
    )
    with pytest.raises(ValidationError, match="no-such-doc"):
        make_document_set(errors=(error,))


def test_set_rejects_duplicate_document_ids() -> None:
    with pytest.raises(ValidationError, match="unique"):
        make_document_set(invoices=(make_invoice(), make_invoice()))


def test_dates_are_real_dates() -> None:
    assert make_invoice().issue_date == date(2026, 10, 6)
