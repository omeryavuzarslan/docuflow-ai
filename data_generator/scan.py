"""Turn a clean digital PDF into an image-only "scan": no text layer, slight skew, blur,
noise and JPEG artefacts. Extraction then has to rely on OCR, like a real scanned page.

All randomness comes from a numpy generator seeded from a string, so the same seed gives
the same pixels. Floats are fine here: these are image parameters, not money.
"""

import hashlib
import io
import time

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageFilter

DPI = 150
# Pillow stamps the current time otherwise, which would make every run's bytes differ.
FIXED_TIMESTAMP = time.gmtime(1_767_225_600)  # 2026-01-01T00:00:00Z


def make_scan(pdf: bytes, seed: str) -> bytes:
    rng = np.random.default_rng(_seed_int(seed))
    document = pdfium.PdfDocument(pdf)
    pages = [_degrade(page.render(scale=DPI / 72).to_pil(), rng) for page in document]
    document.close()

    out = io.BytesIO()
    pages[0].save(
        out,
        "PDF",
        resolution=DPI,
        save_all=True,
        append_images=pages[1:],
        creationDate=FIXED_TIMESTAMP,
        modDate=FIXED_TIMESTAMP,
    )
    return out.getvalue()


def _degrade(image: Image.Image, rng: np.random.Generator) -> Image.Image:
    image = image.convert("L")
    image = image.rotate(
        float(rng.uniform(-1.5, 1.5)), resample=Image.Resampling.BICUBIC, fillcolor=255
    )
    image = image.filter(ImageFilter.GaussianBlur(radius=float(rng.uniform(0.3, 0.9))))

    pixels = np.asarray(image, dtype=np.float32)
    pixels += rng.normal(0.0, float(rng.uniform(6, 14)), size=pixels.shape)
    image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), mode="L")

    # Round-trip through JPEG for compression artefacts, as a scanner app would save it.
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=int(rng.integers(55, 76)))
    return Image.open(io.BytesIO(buffer.getvalue())).convert("L")


def _seed_int(seed: str) -> int:
    return int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8], "big")
