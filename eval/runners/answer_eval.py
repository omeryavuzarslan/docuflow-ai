"""Answer evaluation: correct, cited, honest.

The full /ask path (router -> hybrid retrieval -> answer) on the seed-42 corpus:
- 40 agreement-clause questions and 10 SKU price questions with known answers: is the fact in
  the answer ("60 days", "£25.28")? Does at least one citation point at a passage that really
  contains it? Is every number in the answer present in the cited passages or the question?
- 10 questions the agreements do not answer (warranty, insurance, ...): does the system say so
  instead of inventing an answer?

    uv run --env-file .env python -m eval.runners.answer_eval \\
        --dataset data_generator/output/seed-42 --estimate
"""

import argparse
import json
import random
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from backend.app.db.session import make_engine, make_session_factory
from backend.app.llm.client import PRICES, LLMClient, cost_usd
from backend.app.query.answer import ANSWER_PROMPT_VERSION, answer_question
from backend.app.query.router import ROUTE_PROMPT_VERSION
from backend.app.rag.embeddings import LocalEmbedder
from eval.runners.extraction_eval import CACHE
from eval.runners.retrieval_eval import _contexts, _corpus, _sets, index_corpus
from eval.runners.retrieval_questions import (
    Question,
    build_lookup_questions,
    build_questions,
    is_relevant,
)

TODAY = date(2026, 11, 2)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
UNANSWERABLE = (
    "What warranty period does {s} give {b} on its goods?",
    "What insurance cover must {s} hold under its agreement with {b}?",
    "Who is the named account manager at {s} for {b}?",
    "What discount does {s} give {b} for paying early?",
    "Which courier does {s} use for deliveries to {b}?",
    "What happens if {s} delivers late to {b}: is there a penalty per day?",
    "Can {b} buy from {s} in euros, and at what exchange rate?",
    "What are {s}'s opening hours for {b}'s orders?",
    "Does the agreement between {s} and {b} cover software licences?",
    "What carbon-reporting obligations does {s} have towards {b}?",
)


@dataclass
class AnswerResult:
    id: str
    kind: str
    question: str
    answer: str
    answerable: bool
    intent: str
    expect_answer: bool
    fact_ok: bool | None = None
    citation_ok: bool | None = None
    numbers_grounded: bool | None = None
    abstained_ok: bool | None = None
    cited: list[str] = field(default_factory=list)


def _numbers(text_: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text_)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.runners.answer_eval")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model", default="claude-haiku-5-5", choices=sorted(PRICES))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-cost", type=Decimal, default=Decimal("0.20"))
    parser.add_argument("--estimate", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    args = parser.parse_args(argv)

    files, agreements = _corpus(args.dataset)
    rng = random.Random(f"{args.seed}:answer-eval")
    answerable: list[Question] = (
        rng.sample(build_questions(agreements, args.seed), 40)
        + [
            q
            for q in build_lookup_questions(agreements, _sets(args.dataset), args.seed)
            if q.kind == "sku_price"
        ][:10]
    )
    unanswerable = [
        (f"{a.document_id}:none{i}", t.format(s=a.supplier.name, b=a.buyer.name))
        for i, (a, t) in enumerate(zip(rng.sample(list(agreements), 10), UNANSWERABLE, strict=True))
    ]
    n_questions = len(answerable) + len(unanswerable)

    # Rough upper bound: router call + answer call per question, nothing cached.
    estimate = n_questions * (
        cost_usd(args.model, input_tokens=1500, output_tokens=400)
        + cost_usd(args.model, input_tokens=3000, output_tokens=600)
    )
    print(
        f"{n_questions} questions, expected cost at most ~${estimate:.3f} (limit ${args.max_cost})"
    )
    if args.estimate:
        return 0
    if estimate > args.max_cost:
        print("estimate above --max-cost; not running")
        return 1

    llm = LLMClient(cache_dir=CACHE / "llm")
    embedder = LocalEmbedder()
    factory = make_session_factory(make_engine())
    results: list[AnswerResult] = []
    spent = Decimal(0)
    prefix = "structure:"
    with factory() as session:
        owner, _chunks = index_corpus(
            session, "structure", files, embedder, _contexts(args.dataset)
        )
        session.execute(
            text("SET enable_indexscan = off")
        )  # exact neighbours, as in retrieval eval
        for q in answerable:
            asked = answer_question(session, owner, q.question, llm, embedder, args.model, TODAY)
            spent += asked.cost_usd
            # Grounding: every number in the answer must occur in a passage the model was
            # given (cited or not) or in the question. Otherwise it came from nowhere.
            grounded_in = " ".join(c.text for c in asked.sources) + " " + q.question
            results.append(
                AnswerResult(
                    id=q.id,
                    kind=q.kind,
                    question=q.question,
                    answer=asked.answer,
                    answerable=asked.answerable,
                    intent=asked.intent,
                    expect_answer=True,
                    fact_ok=" ".join(q.fact.split()) in " ".join(asked.answer.split()),
                    citation_ok=any(
                        is_relevant(q, c.document_id.removeprefix(prefix), c.text)
                        for c in asked.citations
                    ),
                    numbers_grounded=_numbers(asked.answer) <= _numbers(grounded_in),
                    cited=[f"{c.filename} / {c.heading}" for c in asked.citations],
                )
            )
        for qid, question in unanswerable:
            asked = answer_question(session, owner, question, llm, embedder, args.model, TODAY)
            spent += asked.cost_usd
            results.append(
                AnswerResult(
                    id=qid,
                    kind="unanswerable",
                    question=question,
                    answer=asked.answer,
                    answerable=asked.answerable,
                    intent=asked.intent,
                    expect_answer=False,
                    abstained_ok=not asked.answerable and not asked.citations,
                    cited=[f"{c.filename} / {c.heading}" for c in asked.citations],
                )
            )

    expected = [r for r in results if r.expect_answer]
    none = [r for r in results if not r.expect_answer]

    def share(values: list[bool | None]) -> float:
        return round(sum(bool(v) for v in values) / len(values), 4)

    summary = {
        "model": args.model,
        "prompts": [ROUTE_PROMPT_VERSION, ANSWER_PROMPT_VERSION],
        "answerable_questions": len(expected),
        "routed_to_search": share([r.intent == "search" for r in expected]),
        "fact_in_answer": share([r.fact_ok for r in expected]),
        "correct_citation": share([r.citation_ok for r in expected]),
        "numbers_grounded": share([r.numbers_grounded for r in expected]),
        "unanswerable_questions": len(none),
        "abstained_correctly": share([r.abstained_ok for r in none]),
        "spent_usd": str(spent),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"answers-{args.dataset.name}-{ANSWER_PROMPT_VERSION}-{args.model}.json"
    out.write_text(
        json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, indent=2) + "\n"
    )

    for key, value in summary.items():
        print(f"{key:>24}: {value:.1%}" if isinstance(value, float) else f"{key:>24}: {value}")
    for r in results:
        bad = (r.expect_answer and not (r.fact_ok and r.citation_ok and r.numbers_grounded)) or (
            not r.expect_answer and not r.abstained_ok
        )
        if bad:
            print(f"  check {r.id}: {r.answer[:140]!r} cited={r.cited}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
