from typing import Literal

from backend.app.domain.types import DomainModel


class Address(DomainModel):
    line1: str
    line2: str | None = None
    city: str
    postcode: str
    country: Literal["GB"] = "GB"


class Party(DomainModel):
    name: str
    vat_number: str
    address: Address


class Supplier(Party):
    """The company that sells the goods and issues the delivery note and invoice."""


class Buyer(Party):
    """The company that raises the purchase order and receives the goods."""
