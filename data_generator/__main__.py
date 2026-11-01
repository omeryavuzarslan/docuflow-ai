"""python -m data_generator --seed 42 --sets 8 [--out DIR] [--force]"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from data_generator.generate import generate
from data_generator.output import write_dataset
from data_generator.plan import MIN_SETS

DEFAULT_OUT = Path(__file__).parent / "output"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m data_generator",
        description="Generate synthetic PO / delivery note / invoice sets with labelled errors.",
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--sets", type=int, default=MIN_SETS, help=f"minimum {MIN_SETS}")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--force", action="store_true", help="replace existing output")
    args = parser.parse_args(argv)

    try:
        sets = generate(args.seed, args.sets)
        root = write_dataset(sets, seed=args.seed, out_dir=args.out, force=args.force)
    except (ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    clean = sum(doc_set.is_clean for doc_set in sets)
    print(f"Wrote {len(sets)} sets ({clean} clean) to {root}")
    for doc_set in sets:
        errors = ", ".join(e.type.value for e in doc_set.errors) or "clean"
        print(f"  {doc_set.set_id}  {doc_set.template:<8} {errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
