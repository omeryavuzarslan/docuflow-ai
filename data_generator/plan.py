"""Which sets are clean, which get which error, and which template each one uses.

Layout: sets 1-2 are clean, then a repeating block of seven sets (one per error type,
then one clean set). For 8 sets that is 2 clean + 6 single-error sets. The layout only
ever appends, so growing `n_sets` never changes an earlier set's plan.
"""

from dataclasses import dataclass

from backend.app.domain.errors import ErrorType

TEMPLATES = ("classic", "modern")
LEADING_CLEAN_SETS = 2
_BLOCK: tuple[ErrorType | None, ...] = (*ErrorType, None)
MIN_SETS = LEADING_CLEAN_SETS + len(ErrorType)


@dataclass(frozen=True)
class SetPlan:
    index: int  # 1-based
    template: str
    error_type: ErrorType | None
    partial_delivery: bool


def make_plan(n_sets: int) -> tuple[SetPlan, ...]:
    if n_sets < MIN_SETS:
        raise ValueError(
            f"need at least {MIN_SETS} sets ({LEADING_CLEAN_SETS} clean + one per error type)"
        )
    return tuple(_plan_for(index) for index in range(1, n_sets + 1))


def _plan_for(index: int) -> SetPlan:
    if index <= LEADING_CLEAN_SETS:
        error_type = None
    else:
        error_type = _BLOCK[(index - LEADING_CLEAN_SETS - 1) % len(_BLOCK)]
    return SetPlan(
        index=index,
        template=TEMPLATES[(index - 1) % len(TEMPLATES)],
        error_type=error_type,
        # Every third set from set 1: a clean set always gets a partial delivery,
        # the false-positive trap (DN below PO quantity is not an error).
        partial_delivery=index % 3 == 1,
    )
