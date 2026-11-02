import pytest

from backend.app.extraction.corrections import InvalidFieldError, apply_corrections, get_field
from backend.app.extraction.schema import ExtractedDocument, ExtractedLine, ExtractedParty

RAW = ExtractedDocument(
    doc_type="invoice",
    document_number="INV-1",
    gross_total="£10.00",
    buyer=ExtractedParty(name="Harbour & Hale Retail ple"),
    lines=(ExtractedLine(sku="A", quantity="9"), ExtractedLine(sku="B", quantity="2")),
)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("document_number", "INV-1"),
        ("buyer.name", "Harbour & Hale Retail ple"),
        ("lines[1].quantity", "2"),
    ],
)
def test_get_field(path: str, value: str) -> None:
    assert get_field(RAW, path) == value


def test_corrections_apply_in_order_and_leave_the_original_untouched() -> None:
    fixed = apply_corrections(
        RAW,
        [
            ("lines[0].quantity", "7"),
            ("lines[0].quantity", "8"),
            ("buyer.name", "Harbour & Hale Retail plc"),
        ],
    )
    assert fixed.lines[0].quantity == "8"
    assert fixed.buyer.name == "Harbour & Hale Retail plc"
    assert RAW.lines[0].quantity == "9"


@pytest.mark.parametrize(
    "path",
    [
        "nope",
        "lines[5].quantity",
        "lines[0].colour",
        "lines",
        "lines[0]",
        "buyer",
        "buyer.age",
        "a b",
        "lines[x].sku",
    ],
)
def test_invalid_paths(path: str) -> None:
    with pytest.raises(InvalidFieldError):
        get_field(RAW, path)
    with pytest.raises(InvalidFieldError):
        apply_corrections(RAW, [(path, "1")])


def test_invalid_document_type_is_rejected() -> None:
    with pytest.raises(InvalidFieldError):
        apply_corrections(RAW, [("doc_type", "receipt")])
