"""Supplier agreements: the long-text documents behind the numbers.

A framework agreement between one supplier and one buyer: payment terms, how and when
prices may change, delivery and returns rules, and a schedule of agreed prices. These are
what retrieval (RAG) is for, and later the source of agreed prices for a contract-price
rule. Like every domain model, the facts are typed; the prose is generated from them.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from backend.app.domain.parties import Buyer, Supplier
from backend.app.domain.types import DomainModel, Money, UnitPrice

Percent = Annotated[Decimal, Field(ge=0, le=1, decimal_places=4)]


class PriceListItem(DomainModel):
    sku: str
    description: str
    unit_price: UnitPrice


class AgreementSection(DomainModel):
    number: int = Field(ge=1)
    heading: str
    text: str


class SupplierAgreement(DomainModel):
    doc_type: Literal["supplier_agreement"] = "supplier_agreement"
    document_id: str
    agreement_number: str
    supplier: Supplier
    buyer: Buyer
    effective_date: date
    term_months: int = Field(ge=1)
    payment_terms_days: int = Field(ge=1)
    late_payment_interest: Percent  # per year above base rate, e.g. 0.08 = 8%
    price_fixed_months: int = Field(ge=0)
    max_price_increase: Percent  # per price review, e.g. 0.05 = 5%
    price_review_notice_days: int = Field(ge=1)
    minimum_order_value: Money
    delivery_lead_days: int = Field(ge=1)
    shortage_report_hours: int = Field(ge=1)
    returns_window_days: int = Field(ge=1)
    termination_notice_days: int = Field(ge=1)
    price_list: tuple[PriceListItem, ...] = Field(min_length=1)
    # The prose as printed, section by section. Generated from the fields above, kept so
    # retrieval evaluation knows exactly which section states which fact.
    sections: tuple[AgreementSection, ...] = Field(min_length=1)
