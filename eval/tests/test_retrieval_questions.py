from backend.app.domain.agreements import SupplierAgreement
from data_generator.agreements import build_agreements
from eval.runners.retrieval_questions import (
    QUESTIONS_PER_AGREEMENT,
    Question,
    build_questions,
    first_relevant_rank,
    is_relevant,
    mean_reciprocal_rank,
    recall_at,
)

AGREEMENTS = build_agreements(42)


def _by_id(document_id: str) -> SupplierAgreement:
    return next(a for a in AGREEMENTS if a.document_id == document_id)


def test_set_size_and_determinism() -> None:
    questions = build_questions(AGREEMENTS, seed=42)
    assert len(questions) == len(AGREEMENTS) * QUESTIONS_PER_AGREEMENT
    assert len({q.id for q in questions}) == len(questions)
    assert build_questions(AGREEMENTS, seed=42) == questions


def test_every_answer_is_really_in_its_agreement() -> None:
    # The labels themselves are checked: each question's evidence occurs in exactly the
    # agreement it points at, so a "miss" can only be a retrieval failure.
    for q in build_questions(AGREEMENTS, seed=42):
        full_text = " ".join(" ".join(s.text.split()) for s in _by_id(q.document_id).sections)
        assert all(e in full_text for e in q.evidence), q


def test_evidence_spans_are_short_enough_for_fixed_windows() -> None:
    assert all(len(e) <= 100 for q in build_questions(AGREEMENTS, seed=42) for e in q.evidence)


def test_questions_name_both_companies() -> None:
    for q in build_questions(AGREEMENTS, seed=42):
        a = _by_id(q.document_id)
        assert a.supplier.name in q.question and a.buyer.name in q.question


def test_relevance_needs_the_right_document_and_all_evidence() -> None:
    q = Question(id="x", kind="k", question="?", document_id="d1", evidence=("60 days", "invoice"))
    assert is_relevant(q, "d1", "pay within 60  days of the invoice date")  # whitespace-tolerant
    assert not is_relevant(q, "d2", "pay within 60 days of the invoice date")
    assert not is_relevant(q, "d1", "pay within 60 days")


def test_rank_and_metrics() -> None:
    q = Question(id="x", kind="k", question="?", document_id="d1", evidence=("yes",))
    assert first_relevant_rank(q, [("d2", "yes"), ("d1", "no"), ("d1", "yes")]) == 3
    assert first_relevant_rank(q, [("d2", "yes")]) is None
    ranks = [1, 3, None, 2]
    assert recall_at(ranks, 1) == 0.25
    assert recall_at(ranks, 5) == 0.75
    assert mean_reciprocal_rank(ranks) == (1 + 1 / 3 + 0 + 1 / 2) / 4


def test_lookup_questions_name_their_code_and_cover_every_set() -> None:
    from data_generator.generate import generate
    from eval.runners.retrieval_questions import build_lookup_questions

    sets = list(generate(42, 8))
    questions = build_lookup_questions(AGREEMENTS, sets, seed=42)
    assert len(questions) == len(AGREEMENTS) + 2 * len(sets)
    assert build_lookup_questions(AGREEMENTS, sets, seed=42) == questions
    for q in questions:
        code = q.evidence[0] if q.kind == "sku_price" else None
        if code:
            assert code in q.question
    invoice_q = next(q for q in questions if q.kind == "invoice_total")
    assert sets[0].invoices[0].invoice_number in invoice_q.question
