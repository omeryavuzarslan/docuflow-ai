# Experiments

Every component has to earn its place with a measured result. Newest first.

## 2026-11-01 — Parsing: Docling on digital PDFs and simulated scans

**Question.** Does Docling recover the values we need from our PDFs, and how much do scans
(OCR) lose?

**Setup.** Dataset `seed-42`, 8 sets, 25 documents (8 PO, 8 DN, 9 invoices), each as a digital
PDF and as a simulated scan (150 dpi greyscale, ±1.5° skew, blur, noise, JPEG q55–75).
Parser `docling 2.145.0`; digital PDFs use the embedded text layer, scans use full-page OCR
(RapidOCR via Docling's "auto" engine). Apple M-series laptop, CPU/MPS defaults.

**Metric.** *Value recall*: of the values a reader needs (document number, dates, totals, and
per line the SKU, quantity, price and amounts, formatted as printed), the share found in the
parsed output. Line values only count if they appear in the same table row as their SKU.
*Line table found*: a table with exactly `lines + 1` rows was detected.
Runner: `uv run python -m eval.runners.parse_eval --dataset data_generator/output/seed-42`.
Raw results: `eval/results/parse-seed-42.json`.

| variant | template | docs | value recall | line table found | median s/doc |
|---|---|---|---|---|---|
| digital | all | 25 | 100.0% | 100% | 1.33 |
| digital | classic | 12 | 100.0% | 100% | 1.51 |
| digital | modern | 13 | 100.0% | 100% | 1.14 |
| scan | all | 25 | 98.8% | 100% | 3.78 |
| scan | classic | 12 | 98.1% | 100% | 3.88 |
| scan | modern | 13 | 99.4% | 100% | 3.78 |

Model warm-up (both pipelines): 20.6 s, once per process.

**What the scan misses look like** (7 values in 5 documents):
- letter/digit confusion: `£0.027` read as `£o.027`, `300mm` as `3oomm`;
- punctuation noise: `CL-2005` read as `CL.-2005`, which also loses that row's quantity
  under our "same row as the SKU" rule;
- a cell left empty (`£7.70` line VAT missing) and a wrapped description moved
  (`66m Packing tape, clear, 48mm x`);
- sub-penny prices (`£0.0183`, `£0.027`) are over-represented: small, dense digits.

**Conclusions.**
- Docling earns its place: tables come out row by row with coordinates on both templates, and
  digital PDFs are lossless.
- Scans are good but not perfect. Extraction (step 3) must not assume clean OCR text. This is
  also why matching rules should compare normalised values (SKU punctuation) and why
  low-confidence fields need human review in the UI.

**Limits.** Only 2 templates and one, fairly light, scan level, all synthetic. Real documents
(DocILE) and harsher scans are planned for the advanced stage; expect lower numbers there.
