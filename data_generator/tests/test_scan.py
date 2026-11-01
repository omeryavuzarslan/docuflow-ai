import io

import pytest
from PIL import Image
from pypdf import PdfReader

from data_generator.build import build_clean_set
from data_generator.plan import SetPlan
from data_generator.render import render_pdf
from data_generator.scan import make_scan


@pytest.fixture(scope="module")
def digital_pdf() -> bytes:
    plan = SetPlan(index=1, template="modern", error_type=None, partial_delivery=False)
    return render_pdf(build_clean_set(42, plan).invoices[0], "modern")


def test_same_seed_gives_identical_bytes(digital_pdf: bytes) -> None:
    assert make_scan(digital_pdf, "42:a") == make_scan(digital_pdf, "42:a")


def test_different_seed_gives_a_different_scan(digital_pdf: bytes) -> None:
    assert make_scan(digital_pdf, "42:a") != make_scan(digital_pdf, "42:b")


def test_scan_has_no_text_layer_and_keeps_page_count(digital_pdf: bytes) -> None:
    scan = PdfReader(io.BytesIO(make_scan(digital_pdf, "42:a")))
    original = PdfReader(io.BytesIO(digital_pdf))
    assert len(scan.pages) == len(original.pages)
    assert all(page.extract_text().strip() == "" for page in scan.pages)


def test_scan_is_a_greyscale_image(digital_pdf: bytes) -> None:
    page = PdfReader(io.BytesIO(make_scan(digital_pdf, "42:a"))).pages[0]
    image = page.images[0].image
    assert isinstance(image, Image.Image)
    assert image.mode == "L"
    assert image.width > 1000  # ~150 dpi A4
