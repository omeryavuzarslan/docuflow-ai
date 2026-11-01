"""Numeric types and the base class shared by every domain model.

Money and quantities are always `Decimal`, never `float`: binary floats cannot represent
most decimal fractions exactly (0.1 + 0.2 != 0.3). Each type also fixes its scale, matching
the Postgres columns: amounts NUMERIC(12,2), unit prices and quantities NUMERIC(12,4).
"""

from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field


class DomainModel(BaseModel):
    """Immutable (`frozen`) and strict about unknown keys (`extra="forbid"`).

    Changes are made with `model_copy(update=...)`, which returns a new object, so a
    clean ground-truth document can never be modified by accident.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("float is not allowed for amounts; pass a Decimal, str or int")
    return value


def _at_scale(places: int) -> AfterValidator:
    # The decimal_places check has already guaranteed this loses nothing. It only fixes
    # the representation ("1E+2" -> "100.00") so serialised output is byte-stable.
    exponent = Decimal(1).scaleb(-places)
    return AfterValidator(lambda value: value.quantize(exponent))


Money = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(max_digits=12, decimal_places=2),
    _at_scale(2),
]
UnitPrice = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(ge=0, max_digits=12, decimal_places=4),
    _at_scale(4),
]
Quantity = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(gt=0, max_digits=12, decimal_places=4),
    _at_scale(4),
]
VatRate = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(ge=0, le=1, decimal_places=4),
    _at_scale(4),
]
