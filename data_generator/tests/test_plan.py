import pytest

from backend.app.domain.errors import ErrorType
from data_generator.plan import MIN_SETS, TEMPLATES, make_plan


def test_minimum_plan_has_two_clean_sets_and_every_error_type_once() -> None:
    plan = make_plan(MIN_SETS)
    assert MIN_SETS == 8
    assert sum(p.error_type is None for p in plan) == 2
    errors = [p.error_type for p in plan if p.error_type is not None]
    assert sorted(errors) == sorted(ErrorType)


def test_at_least_one_clean_set_has_a_partial_delivery() -> None:
    plan = make_plan(MIN_SETS)
    assert any(p.error_type is None and p.partial_delivery for p in plan)


@pytest.mark.parametrize("n_sets", [8, 9, 13, 30])
def test_larger_plans_cover_every_error_type_with_one_error_per_set(n_sets: int) -> None:
    plan = make_plan(n_sets)
    assert [p.index for p in plan] == list(range(1, n_sets + 1))
    assert sum(p.error_type is None for p in plan) >= 2
    assert {p.error_type for p in plan if p.error_type is not None} == set(ErrorType)


def test_both_templates_are_used() -> None:
    assert {p.template for p in make_plan(MIN_SETS)} == set(TEMPLATES)


@pytest.mark.parametrize(("small", "large"), [(8, 9), (8, 30), (13, 14)])
def test_growing_the_plan_keeps_earlier_sets_unchanged(small: int, large: int) -> None:
    assert make_plan(large)[:small] == make_plan(small)


def test_too_few_sets_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="at least 8"):
        make_plan(5)
