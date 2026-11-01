import pytest

from data_generator.build import build_clean_set
from data_generator.plan import SetPlan
from data_generator.tests.helpers import assert_set_consistent

SEEDS = range(50)


def _plan(index: int = 1, partial_delivery: bool = False) -> SetPlan:
    return SetPlan(
        index=index, template="classic", error_type=None, partial_delivery=partial_delivery
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_clean_sets_are_consistent(seed: int) -> None:
    assert_set_consistent(build_clean_set(seed, _plan()))
    assert_set_consistent(build_clean_set(seed, _plan(partial_delivery=True)))


@pytest.mark.parametrize("seed", SEEDS)
def test_partial_delivery_short_ships_exactly_one_line(seed: int) -> None:
    doc_set = build_clean_set(seed, _plan(partial_delivery=True))
    ordered = {line.sku: line.quantity for line in doc_set.purchase_order.lines}
    short = [
        line for line in doc_set.delivery_note.lines if line.quantity_delivered < ordered[line.sku]
    ]
    assert len(short) == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_full_delivery_ships_everything(seed: int) -> None:
    doc_set = build_clean_set(seed, _plan())
    ordered = {line.sku: line.quantity for line in doc_set.purchase_order.lines}
    delivered = {line.sku: line.quantity_delivered for line in doc_set.delivery_note.lines}
    assert delivered == ordered


def test_same_inputs_give_the_same_set() -> None:
    assert build_clean_set(42, _plan(3)) == build_clean_set(42, _plan(3))


def test_different_seed_or_index_gives_a_different_set() -> None:
    base = build_clean_set(42, _plan(3))
    assert build_clean_set(43, _plan(3)) != base
    assert build_clean_set(42, _plan(4)).purchase_order != base.purchase_order


def test_ids_and_numbers_include_the_set_index() -> None:
    doc_set = build_clean_set(42, _plan(7))
    assert doc_set.set_id == "set-007"
    assert doc_set.purchase_order.document_id == "set-007-po"
    assert doc_set.delivery_note.document_id == "set-007-dn"
    assert doc_set.invoices[0].document_id == "set-007-inv-1"


def test_document_numbers_are_unique_across_sets() -> None:
    sets = [build_clean_set(42, _plan(i)) for i in range(1, 31)]
    numbers = [s.purchase_order.po_number for s in sets]
    numbers += [s.delivery_note.dn_number for s in sets]
    numbers += [s.invoices[0].invoice_number for s in sets]
    assert len(numbers) == len(set(numbers))


def test_line_counts_stay_in_range() -> None:
    for seed in SEEDS:
        assert 3 <= len(build_clean_set(seed, _plan()).purchase_order.lines) <= 8


def test_some_prices_use_four_decimal_places() -> None:
    # The catalogue includes sub-penny unit prices so rounding is exercised for real.
    prices = [
        line.unit_price
        for seed in SEEDS
        for line in build_clean_set(seed, _plan()).purchase_order.lines
    ]
    assert any(price != price.quantize(price.__class__("0.01")) for price in prices)
