from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder
from backend.app.extraction.schema import ExtractedLine
from backend.tests.unit.extraction.printed import printed
from data_generator.build import build_clean_set
from data_generator.plan import SetPlan
from eval.runners.extraction_eval import score_extraction


def _invoice() -> Invoice:
    plan = SetPlan(index=1, template="classic", error_type=None, partial_delivery=False)
    return build_clean_set(5, plan).invoices[0]


def test_a_perfect_extraction_scores_every_field() -> None:
    for truth in _documents():
        checks, extra = score_extraction(truth, printed(truth))
        assert all(c.correct for c in checks), [c for c in checks if not c.correct]
        assert extra == 0


def _documents() -> list[PurchaseOrder | DeliveryNote | Invoice]:
    plan = SetPlan(index=1, template="classic", error_type=None, partial_delivery=True)
    s = build_clean_set(5, plan)
    return [s.purchase_order, s.delivery_note, s.invoices[0]]


def test_formatting_differences_are_not_errors() -> None:
    truth = _invoice()
    raw = printed(truth)
    raw = raw.model_copy(
        update={"gross_total": raw.gross_total.replace("£", "GBP ").replace(",", "")}
    )
    checks, _ = score_extraction(truth, raw)
    assert all(c.correct for c in checks)


def test_a_wrong_digit_is_an_error_on_that_field_only() -> None:
    truth = _invoice()
    raw = printed(truth)
    line = raw.lines[0].model_copy(update={"quantity": "999"})
    checks, _ = score_extraction(truth, raw.model_copy(update={"lines": (line, *raw.lines[1:])}))
    wrong = [c.path for c in checks if not c.correct]
    assert wrong == [f"lines[{truth.lines[0].sku}].quantity"]


def test_missing_and_extra_lines() -> None:
    truth = _invoice()
    raw = printed(truth)
    invented = ExtractedLine(sku="ZZ-0000", quantity="1")
    checks, extra = score_extraction(
        truth, raw.model_copy(update={"lines": (*raw.lines[1:], invented)})
    )
    assert extra == 1
    missing_sku = truth.lines[0].sku
    assert all(not c.correct for c in checks if c.path.startswith(f"lines[{missing_sku}]"))


def test_wrong_document_type() -> None:
    truth = _invoice()
    checks, _ = score_extraction(
        truth, printed(truth).model_copy(update={"doc_type": "delivery_note"})
    )
    assert [c.path for c in checks if not c.correct] == ["doc_type"]
