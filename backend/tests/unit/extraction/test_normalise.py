from datetime import date
from decimal import Decimal

import pytest

from backend.app.extraction.normalise import (
    parse_amount,
    parse_date,
    parse_quantity,
    parse_rate,
    to_domain,
)
from backend.app.extraction.schema import ExtractedDocument
from backend.tests.unit.extraction.printed import printed
from data_generator.build import build_clean_set
from data_generator.plan import SetPlan

D = Decimal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£1,234.56", D("1234.56")),
        ("  £5.29 ", D("5.29")),
        ("£0.0609", D("0.0609")),
        ("GBP 883.95", D("883.95")),
        ("£ 1 234.00", D("1234.00")),
        ("-£2.50", D("-2.50")),
    ],
)
def test_parse_amount(text: str, expected: Decimal) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["£o.027", "", "abc", "£1.2.3", "12,34"])
def test_parse_amount_rejects_garbage(text: str) -> None:
    # Python does not guess: an OCR error like "o" for "0" is a failed field, not a fix.
    with pytest.raises(ValueError):
        parse_amount(text)


def test_parse_quantity() -> None:
    assert parse_quantity("1,400") == D("1400")
    assert parse_quantity("2.5") == D("2.5")
    with pytest.raises(ValueError):
        parse_quantity("£3")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("20%", D("0.20")), ("20", D("0.20")), ("5 %", D("0.05")), ("0.20", D("0.20"))],
)
def test_parse_rate(text: str, expected: Decimal) -> None:
    assert parse_rate(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("06/03/2026", date(2026, 3, 6)),  # UK: day first
        ("2026-03-06", date(2026, 3, 6)),
        ("6 March 2026", date(2026, 3, 6)),
    ],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text) == expected


def test_parse_date_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_date("31/02/2026")


@pytest.mark.parametrize("seed", range(10))
def test_printed_values_convert_back_to_the_exact_domain_documents(seed: int) -> None:
    # Ties the extraction schema to the domain models: every field a document has can be
    # read off the page and turned back into the same document.
    plan = SetPlan(index=1, template="classic", error_type=None, partial_delivery=True)
    doc_set = build_clean_set(seed, plan)
    for truth in (doc_set.purchase_order, doc_set.delivery_note, doc_set.invoices[0]):
        document, errors = to_domain(printed(truth), truth.document_id)
        assert errors == ()
        assert document == truth


def test_conversion_collects_every_error_instead_of_stopping_at_the_first() -> None:
    plan = SetPlan(index=1, template="classic", error_type=None, partial_delivery=False)
    truth = build_clean_set(1, plan).invoices[0]
    raw = printed(truth)
    bad_line = raw.lines[0].model_copy(update={"unit_price": "£o.027"})
    raw = raw.model_copy(
        update={"lines": (bad_line, *raw.lines[1:]), "gross_total": "", "due_date": "soon"}
    )
    document, errors = to_domain(raw, truth.document_id)
    assert document is None
    assert any("lines[0].unit_price" in e for e in errors)
    assert any("gross_total" in e for e in errors)
    assert any("due_date" in e for e in errors)


def test_other_documents_are_not_converted() -> None:
    document, errors = to_domain(ExtractedDocument(doc_type="other"), "x")
    assert document is None
    assert errors == ("doc_type: not a purchase order, delivery note or invoice",)
