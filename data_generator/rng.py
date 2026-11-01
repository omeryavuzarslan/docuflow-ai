import random
from decimal import Decimal


def make_rng(seed: int, set_index: int, purpose: str) -> random.Random:
    """An independent random stream per (seed, set, purpose).

    Seeding with a string is deterministic across runs (unlike `hash()`, which Python
    randomises per process). Separate streams mean that adding a set, or changing how
    errors are injected, never shifts the random values used for other sets or for the
    clean documents.
    """
    return random.Random(f"{seed}:{set_index}:{purpose}")


def random_decimal(rng: random.Random, low: int, high: int, places: int) -> Decimal:
    """A Decimal in [low, high] * 10**-places, drawn as an integer so no float is involved.

    random_decimal(rng, 1599, 2499, 2) -> a price between 15.99 and 24.99.
    """
    return Decimal(rng.randint(low, high)).scaleb(-places)
