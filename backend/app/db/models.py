"""Database tables (SQLAlchemy 2.0).

These are deliberately separate from the Pydantic domain models: tables describe storage
(keys, owners, timestamps, indexes), domain models describe documents. `mapping.py`
converts between the two and a round-trip test keeps them in step.

Two kinds of data:
- queried and summed (documents, amounts, lines, findings, jobs): real columns, money as
  NUMERIC(12,2), prices and quantities NUMERIC(12,4);
- stored and read back whole (parser output, raw LLM output, provenance): JSONB.

Every table carries `owner_id`; every query must filter on it.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(12, 2)
PRECISE = Numeric(12, 4)  # unit prices and quantities
RATE = Numeric(5, 4)
USD_COST = Numeric(12, 6)  # API costs are fractions of a cent

Json = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    # Predictable constraint names, so Alembic can find them in later migrations.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def _uuid() -> str:
    return str(uuid.uuid4())


class _Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class _Owned:
    owner_id: Mapped[str] = mapped_column(String(64), index=True)


# --- uploaded files and what was read from them --------------------------------------


class DocumentRow(_Owned, _Timestamps, Base):
    """One uploaded file. Its id is the domain `document_id`."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("owner_id", "sha256", name="uq_documents_owner_sha256"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    # Arrival order. Timestamps can tie (one transaction, one now()); this cannot. Used to
    # decide which of two identical invoices is the original.
    received_seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str | None] = mapped_column(String(512))
    # queued | processing | done | needs_review | failed
    status: Mapped[str] = mapped_column(String(20), default="queued")
    doc_type: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ParseRow(_Owned, _Timestamps, Base):
    __tablename__ = "parses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    parser: Mapped[str] = mapped_column(String(64))
    ocr: Mapped[bool] = mapped_column(Boolean)
    data: Mapped[dict[str, Any]] = mapped_column(Json)  # ParsedDocument as JSON


class ExtractionRow(_Owned, _Timestamps, Base):
    """What the LLM returned, exactly. Never updated: re-processing adds a new version."""

    __tablename__ = "extractions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_extractions_document_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    raw: Mapped[dict[str, Any]] = mapped_column(Json)
    conversion_errors: Mapped[list[str]] = mapped_column(Json)
    provenance: Mapped[dict[str, Any]] = mapped_column(Json)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(USD_COST)  # cost of the original API call
    # True when served from the LLM cache: nothing was spent for this row, so spend reports
    # must sum cost_usd over cached = false only.
    cached: Mapped[bool] = mapped_column(Boolean, server_default="false")


class CorrectionRow(_Owned, _Timestamps, Base):
    """A person's change to one extracted field. Kept apart from the raw extraction, so we
    always know what the model read and what a person changed."""

    __tablename__ = "corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Order of application; timestamps can tie inside one transaction.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    extraction_id: Mapped[str] = mapped_column(ForeignKey("extractions.id", ondelete="CASCADE"))
    field: Mapped[str] = mapped_column(String(128))  # e.g. "lines[2].quantity"
    old_value: Mapped[str] = mapped_column(Text)
    new_value: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(255))


# --- the three document types, as typed rows ------------------------------------------


class _Parties:
    """Supplier and buyer stored inline: each document has exactly one of each."""

    supplier_name: Mapped[str] = mapped_column(String(255))
    supplier_vat_number: Mapped[str] = mapped_column(String(32), index=True)
    supplier_address_line1: Mapped[str] = mapped_column(String(255))
    supplier_address_line2: Mapped[str | None] = mapped_column(String(255))
    supplier_city: Mapped[str] = mapped_column(String(128))
    supplier_postcode: Mapped[str] = mapped_column(String(16))
    supplier_country: Mapped[str] = mapped_column(String(2))
    buyer_name: Mapped[str] = mapped_column(String(255))
    buyer_vat_number: Mapped[str] = mapped_column(String(32))
    buyer_address_line1: Mapped[str] = mapped_column(String(255))
    buyer_address_line2: Mapped[str | None] = mapped_column(String(255))
    buyer_city: Mapped[str] = mapped_column(String(128))
    buyer_postcode: Mapped[str] = mapped_column(String(16))
    buyer_country: Mapped[str] = mapped_column(String(2))


class _DocumentKey:
    # SQLAlchemy 2 copies mixin columns, foreign keys included, into each table.
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )


class _LineBase:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position: Mapped[int] = mapped_column(Integer)  # order on the page, 0-based
    line_no: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)


class PurchaseOrderRow(_DocumentKey, _Owned, _Parties, Base):
    __tablename__ = "purchase_orders"

    po_number: Mapped[str] = mapped_column(String(64), index=True)
    issue_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    net_total: Mapped[Decimal] = mapped_column(MONEY)
    lines: Mapped[list["POLineRow"]] = relationship(
        order_by="POLineRow.position", cascade="all, delete-orphan", lazy="selectin"
    )


class POLineRow(_LineBase, Base):
    __tablename__ = "purchase_order_lines"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_orders.document_id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(PRECISE)
    unit_price: Mapped[Decimal] = mapped_column(PRECISE)
    vat_rate: Mapped[Decimal] = mapped_column(RATE)
    line_net: Mapped[Decimal] = mapped_column(MONEY)


class DeliveryNoteRow(_DocumentKey, _Owned, _Parties, Base):
    __tablename__ = "delivery_notes"

    dn_number: Mapped[str] = mapped_column(String(64), index=True)
    po_number: Mapped[str] = mapped_column(String(64), index=True)
    delivery_date: Mapped[date] = mapped_column(Date)
    lines: Mapped[list["DNLineRow"]] = relationship(
        order_by="DNLineRow.position", cascade="all, delete-orphan", lazy="selectin"
    )


class DNLineRow(_LineBase, Base):
    __tablename__ = "delivery_note_lines"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_notes.document_id", ondelete="CASCADE"), index=True
    )
    quantity_delivered: Mapped[Decimal] = mapped_column(PRECISE)


class InvoiceRow(_DocumentKey, _Owned, _Parties, Base):
    __tablename__ = "invoices"

    invoice_number: Mapped[str] = mapped_column(String(64), index=True)
    po_number: Mapped[str] = mapped_column(String(64), index=True)
    delivery_note_numbers: Mapped[list[str]] = mapped_column(ARRAY(String(64)))
    issue_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    net_total: Mapped[Decimal] = mapped_column(MONEY)
    vat_total: Mapped[Decimal] = mapped_column(MONEY)
    gross_total: Mapped[Decimal] = mapped_column(MONEY)
    lines: Mapped[list["InvoiceLineRow"]] = relationship(
        order_by="InvoiceLineRow.position", cascade="all, delete-orphan", lazy="selectin"
    )


class InvoiceLineRow(_LineBase, Base):
    __tablename__ = "invoice_lines"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("invoices.document_id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(PRECISE)
    unit_price: Mapped[Decimal] = mapped_column(PRECISE)
    vat_rate: Mapped[Decimal] = mapped_column(RATE)
    line_net: Mapped[Decimal] = mapped_column(MONEY)
    line_vat: Mapped[Decimal] = mapped_column(MONEY)


# --- findings and the job queue ------------------------------------------------------


class DiscrepancyRow(_Owned, _Timestamps, Base):
    __tablename__ = "discrepancies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    rule: Mapped[str] = mapped_column(String(8))
    type: Mapped[str] = mapped_column(String(32))
    field: Mapped[str | None] = mapped_column(String(128))
    expected: Mapped[str | None] = mapped_column(Text)
    actual: Mapped[str | None] = mapped_column(Text)
    related_document_id: Mapped[str | None] = mapped_column(String(64))
    amount_impact: Mapped[Decimal | None] = mapped_column(MONEY)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved | dismissed


class JobRow(_Owned, _Timestamps, Base):
    """The job queue. Workers claim rows with SELECT ... FOR UPDATE SKIP LOCKED."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(Json)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
