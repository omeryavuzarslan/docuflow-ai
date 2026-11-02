"""Render documents to PDF: Jinja2 fills an HTML template, WeasyPrint turns it into a PDF.

The PDF shows each document exactly as stored, including any injected error. Formatting
(GBP, DD/MM/YYYY) lives here, in the presentation layer; the ground truth keeps ISO dates
and plain Decimals.
"""

import importlib
import os
import sys
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path
from types import ModuleType

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from backend.app.domain.agreements import SupplierAgreement
from backend.app.domain.document_set import DocumentSet
from backend.app.domain.documents import DeliveryNote, Invoice, PurchaseOrder
from data_generator.plan import TEMPLATES

Document = PurchaseOrder | DeliveryNote | Invoice

TEMPLATE_DIR = Path(__file__).parent / "templates"


def format_money(value: Decimal) -> str:
    return f"£{value:,.2f}"


def format_price(value: Decimal) -> str:
    """At least 2 decimal places, more only when the price really has them (£0.045)."""
    return f"£{value:,.{max(2, _significant_places(value))}f}"


def format_quantity(value: Decimal) -> str:
    return f"{value:,.{_significant_places(value)}f}"


def format_vat_rate(value: Decimal) -> str:
    return f"{format_quantity(value * 100)}%"


def format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _significant_places(value: Decimal) -> int:
    """Decimal places without trailing zeros: 2.5000 -> 1, 2400.0000 -> 0."""
    exponent = value.normalize().as_tuple().exponent
    assert isinstance(exponent, int)  # finite: the domain types reject NaN and Infinity
    return max(0, -exponent)


@cache
def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        # Escapes "&" and "<" in data, so a name like "Harbour & Hale" cannot break the HTML.
        autoescape=select_autoescape(["html", "j2"]),
        # A typo in a template variable fails loudly instead of rendering as blank.
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        money=format_money,
        price=format_price,
        qty=format_quantity,
        vat_rate=format_vat_rate,
        uk_date=format_date,
    )
    return env


def render_html(document: Document, template: str) -> str:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template {template!r}; expected one of {TEMPLATES}")
    return _environment().get_template(f"{template}.html.j2").render(doc=document)


def render_pdf(document: Document, template: str) -> bytes:
    html = render_html(document, template)
    weasyprint = _import_weasyprint()
    pdf: bytes = weasyprint.HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf()
    return pdf


def render_agreement_pdf(agreement: SupplierAgreement) -> bytes:
    html = _environment().get_template("agreement.html.j2").render(a=agreement)
    pdf: bytes = _import_weasyprint().HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf()
    return pdf


def write_pdfs(doc_set: DocumentSet, set_dir: Path) -> dict[str, str]:
    """Write one PDF per document; returns {document_id: file name}."""
    documents: list[Document] = [
        doc_set.purchase_order,
        doc_set.delivery_note,
        *doc_set.invoices,
    ]
    files = {}
    for document in documents:
        name = document.document_id.removeprefix(f"{doc_set.set_id}-") + ".pdf"
        (set_dir / name).write_bytes(render_pdf(document, doc_set.template))
        files[document.document_id] = name
    return files


@cache
def _import_weasyprint() -> ModuleType:
    """Import WeasyPrint lazily, after making Homebrew's libraries findable on macOS.

    WeasyPrint loads Pango and friends with dlopen by bare name. A uv-managed Python does
    not search Homebrew's lib directory, so we add it to the dyld fallback path first.
    """
    if sys.platform == "darwin":
        lib = Path(os.environ.get("HOMEBREW_PREFIX", "/opt/homebrew")) / "lib"
        paths = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "/usr/local/lib:/usr/lib")
        if lib.is_dir() and str(lib) not in paths.split(":"):
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{lib}:{paths}"
    # import_module rather than `import`: WeasyPrint ships no type hints.
    return importlib.import_module("weasyprint")
