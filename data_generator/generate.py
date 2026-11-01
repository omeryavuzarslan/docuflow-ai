from backend.app.domain.document_set import DocumentSet
from data_generator.build import build_clean_set
from data_generator.inject import inject_error
from data_generator.plan import make_plan
from data_generator.rng import make_rng


def generate(seed: int, n_sets: int) -> tuple[DocumentSet, ...]:
    """Build every set in the plan: clean first, then inject its error, if any."""
    sets = []
    for plan in make_plan(n_sets):
        doc_set = build_clean_set(seed, plan)
        if plan.error_type is not None:
            rng = make_rng(seed, plan.index, "inject")
            doc_set = inject_error(doc_set, plan.error_type, rng)
        sets.append(doc_set)
    return tuple(sets)
