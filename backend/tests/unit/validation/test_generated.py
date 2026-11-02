"""The strongest check: on generated data, the rules find every injected error exactly
once, with the right type, and nothing else (including partial deliveries)."""

import pytest

from backend.app.validation.rules import Document, validate
from data_generator.generate import generate


@pytest.mark.parametrize("seed", range(40))
def test_rules_find_exactly_the_injected_errors(seed: int) -> None:
    sets = generate(seed, 15)  # 2 clean, 6 errors, clean, 6 errors
    documents: list[Document] = []
    for s in sets:
        documents += [s.purchase_order, s.delivery_note, *s.invoices]
    truth = {(e.document_id, e.type.value) for s in sets for e in s.errors}

    found = validate(documents).discrepancies

    predicted = [(d.document_id, d.type) for d in found]
    assert sorted(predicted) == sorted(truth)  # also: no error reported twice
