import io
import json
from pathlib import Path

from pypdf import PdfReader

from backend.app.domain.agreements import SupplierAgreement
from data_generator.agreements import build_agreements
from data_generator.catalog import BUYERS, SUPPLIERS
from data_generator.render import render_agreement_pdf


def _section(a: SupplierAgreement, heading: str) -> str:
    return next(s.text for s in a.sections if s.heading == heading)


def test_one_agreement_per_supplier_and_buyer_pair() -> None:
    agreements = build_agreements(42)
    assert len(agreements) == len(SUPPLIERS) * len(BUYERS)
    pairs = {(a.supplier.vat_number, a.buyer.vat_number) for a in agreements}
    assert len(pairs) == len(agreements)
    assert len({a.agreement_number for a in agreements}) == len(agreements)


def test_same_seed_same_agreements_different_seed_different_terms() -> None:
    assert build_agreements(42) == build_agreements(42)
    assert build_agreements(42) != build_agreements(43)


def test_every_fact_is_stated_in_its_section() -> None:
    # Retrieval evaluation relies on this: the answer to a question is in a known section.
    for a in build_agreements(42):
        assert f"{a.payment_terms_days} days" in _section(a, "Invoicing and payment")
        assert f"{a.max_price_increase * 100:.0f}%" in _section(a, "Prices and price review")
        assert f"{a.price_review_notice_days} days" in _section(a, "Prices and price review")
        assert f"{a.price_fixed_months} months" in _section(a, "Prices and price review")
        assert f"{a.delivery_lead_days} working days" in _section(a, "Orders and delivery")
        assert f"{a.shortage_report_hours} hours" in _section(a, "Shortages, damage and returns")
        assert f"{a.returns_window_days} days" in _section(a, "Shortages, damage and returns")
        assert f"{a.termination_notice_days} days" in _section(a, "Termination")
        assert a.agreement_number in _section(a, "Parties and term")
        schedule = _section(a, "Schedule 1: Price list")
        assert all(item.sku in schedule for item in a.price_list)


def test_clauses_are_not_all_worded_the_same() -> None:
    wordings = {_section(a, "Invoicing and payment").split(".")[1] for a in build_agreements(42)}
    assert len(wordings) > 1


def test_agreement_pdf_contains_its_terms(tmp_path: Path) -> None:
    a = build_agreements(42)[0]
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(render_agreement_pdf(a))).pages)
    for expected in (
        a.agreement_number,
        a.supplier.name,
        a.buyer.name,
        "Schedule 1",
        a.price_list[0].sku,
    ):
        assert expected in text
    assert f"{a.payment_terms_days}" in text


def test_dataset_output_includes_agreements(tmp_path: Path) -> None:
    from data_generator.generate import generate
    from data_generator.output import write_dataset

    root = write_dataset(
        generate(42, 8), 42, tmp_path, render_pdfs=False, agreements=build_agreements(42)
    )
    manifest = json.loads((root / "manifest.json").read_text())
    assert len(manifest["agreements"]) == 15
    first = manifest["agreements"][0]
    restored = SupplierAgreement.model_validate_json((root / first["json"]).read_bytes())
    assert restored == build_agreements(42)[0]
