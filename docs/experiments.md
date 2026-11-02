# Experiments

Every component has to earn its place with a measured result. Newest first.

## 2026-11-02 — Retrieval v1: chunking strategies (dense, bge-small, pgvector)

**Question.** Does structure-aware chunking beat fixed-size windows, and what is the
document-context prefix on every chunk worth?

**Setup.** Corpus: 15 supplier agreements (near-identical apart from parties and terms) plus
the 25 digital POs, delivery notes and invoices of `seed-42` as distractors, all parsed with
Docling (parse-v2). 120 questions (8 per agreement, sampled from 11 templates), each labelled
with its agreement and a short evidence span built from the typed terms, before any retrieval
code ran; a test checks every label. A hit is relevant if it comes from the right agreement
and contains the evidence. Embeddings: local `BAAI/bge-small-en-v1.5` (384-d). Search: the
production `search` (pgvector, owner-scoped), k = 10. Runner:
`eval/runners/retrieval_eval.py`. Raw: `eval/results/retrieval-seed-42.json`. Cost: $0.

| strategy | chunks | Recall@1 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| **structure + context line** | 494 | **74.2%** | **96.7%** | **98.3%** | **0.835** |
| structure, no context line | 494 | 0.0% | 0.0% | 4.2% | 0.006 |
| fixed 500-char windows (100 overlap) | 145 | 21.7% | 30.0% | 33.3% | 0.256 |

Median search latency ≈ 20 ms for all three.

**Why the context line matters so much.** The questions name both companies ("How many days
does Harbour & Hale have to pay invoices from Kestrel?"). Without the prefix only section 1
("Parties and term") contains those names, so in 77 of 120 questions the top hit was the
*right agreement's wrong clause*. Fixed windows fail the same way: the window with the
names wins. The prefix lets one chunk carry both "who" and "what".

**Where structure + context still misses (31 questions not at rank 1).**
- *Minimum order value* (recall@1 0.10): the question ("smallest order Harbour & Hale may place
  with Kestrel") matches the header chunks of the purchase orders, which carry both company
  names and the word "order".
- *Price fixed period* 0.55, *late interest* 0.64: near-duplicate wording across clauses of
  the same contract.
- Docling reads the modern template's letter-spaced titles as "DEL I VERY NOTE"; harmless here,
  but it degrades keyword search later.

**Conclusions.**
- Structure-aware chunks with a document-context prefix are the default; both parts earn their
  place (fixed: 3x lower Recall@1; no prefix: unusable on near-identical contracts).
- 97% of answers are in the top 5, which is what an answer-generation step (step 7) consumes.
- Next levers, to measure in step 7: a query router / document-type filter (agreement questions
  should not compete with POs), hybrid search (Postgres FTS + RRF) for exact terms such as SKUs
  and numbers.

**Limits.** Template questions with both names spelled out are easier than real users' questions;
one embedding model; synthetic agreements. Paraphrased and under-specified questions (no company
names) are planned with the step 7 router.

## 2026-11-02 — Discrepancy detection: rules alone and end to end

**Question.** Do the rules (R1–R8, ADR-0002) find the injected errors without false alarms,
on perfect data and after PDF parsing + LLM extraction?

**Setup.** A finding is a hit when (document_id, type) matches an injected error. Runner:
`eval/runners/discrepancy_eval.py`.
- *Rules alone:* 100 generated sets (seed 7; 16 clean incl. partial deliveries, 84 errors).
- *End to end:* seed-42 PDFs -> Docling (parse-v2) -> Haiku 5.5 (extract-v2, cached, $0) ->
  rules. Documents whose extraction could not be converted go to human review.

| run | precision | recall | false alarms | notes |
|---|---|---|---|---|
| rules alone (100 sets) | 100% | 100% (84/84) | 0 | 0 on clean sets |
| end to end, digital | 100% | 100% (6/6) | 0 | |
| end to end, scan (first try) | 62.5% | 83.3% (5/6) | 3 | |
| end to end, scan (final) | **100%** | 83.3% (5/6) | **0** | the 1 miss is in a document already sent to review |

**What the first scan run showed.** All three false alarms were *knock-on* effects of OCR:
- the scanned PO of set-002 lost its supplier block, went to review, and its delivery note
  and invoice were then flagged as "no matching PO";
- set-006's delivery note was read with SKU `CL.-2005`, so the invoice line `CL-2005` looked
  undelivered and R1 fired.

**Fixes.** Checks that depend on a document under review are held rather than run, and SKUs
are compared on letters and digits only (ADR-0002). Both have unit tests.

**Conclusions.**
- The rules are exact on correct data (also checked by a 40-seed property test in CI).
- End to end on digital PDFs: every error found, no false alarms.
- On scans the system does not raise false alarms; what it cannot read goes to a person
  (2 of 25 documents), and the one missed error is inside one of those.
- Limits: 6 injected errors per end-to-end run is small; one scan level; synthetic layouts.

## 2026-11-02 — Extraction v2: parser keeps page headers, prompt v2 (Haiku 5.5)

**Question.** Do the parse-v2 and prompt-v2 fixes remove the v1 failures?

**Setup.** As v1, with parse-v2 (Docling body + furniture layers) and `extract-v2`. Haiku 5.5
only, to verify the fix cheaply. Raw: `eval/results/extraction-seed-42-extract-v2.json`.

| model | variant | type | header | lines | docs fully correct | unverified | $/doc | median s |
|---|---|---|---|---|---|---|---|---|
| Haiku 5.5 | digital | 100% | **100.0%** (v1 90.9%) | 100.0% | **100%** (v1 48%) | 1.8% | 0.0007 | 3.2 |
| Haiku 5.5 | scan | 100% | **97.7%** (v1 93.6%) | 99.5% | **80%** (v1 48%) | 2.4% | 0.0007 | 3.0 |

Cost of the run: $0.035.

**Remaining errors (all on scans, 8 fields in 5 documents):** OCR misreads copied through
(`plc` read as `ple`, 3×), the issuer block of one scanned PO not recognised, one table cell
OCR left empty (correctly reported as empty, not guessed), and one SKU with OCR punctuation
noise (`CL.-2005`) that the model dropped together with its quantity.

**Conclusions.**
- On digital PDFs the pipeline is now exact: every field of every document, at $0.0007 per
  document with the cheapest model.
- Scans are the remaining gap, and it is an OCR gap: the model copies what OCR produced.
  Candidates for later: a stronger OCR engine or higher scan DPI (measure parse recall first),
  and human review of fields that fail conversion or provenance lookup.
- Model choice: Haiku 5.5 as the default extractor. Sonnet/Opus did not beat it on v1 beyond
  noise and cost 19-37× more; re-run them on v2 only if the budget allows.

## 2026-11-02 — Extraction v1: Claude Haiku 5.5 vs Sonnet 5.5 vs Opus 5.5

**Question.** How accurately does one structured-output call classify and extract each
document, and is the cheaper model good enough?

**Setup.** Dataset `seed-42` (25 documents × digital/scan), parse-v1 (Docling body layer
only), prompt `extract-v1`, `messages.parse()` with the `ExtractedDocument` schema, effort
`low`, no fallbacks. Fields are compared after parsing (`£1,234.56` == 1234.56); lines are
matched by SKU; the truth is the document as written, injected errors included.
Runner: `eval/runners/extraction_eval.py`. Raw: `eval/results/extraction-seed-42-extract-v1.json`.

| model | variant | type | header | lines | docs fully correct | unverified | $/doc | median s |
|---|---|---|---|---|---|---|---|---|
| Haiku 5.5 | digital | 100% | 90.9% | 100.0% | 48% | 1.2% | 0.0007 | 3.2 |
| Haiku 5.5 | scan | 100% | 93.6% | 99.5% | 48% | 2.5% | 0.0007 | 3.6 |
| Sonnet 5.5 | digital | 100% | 92.7% | 100.0% | 48% | 1.0% | 0.0131 | 4.2 |
| Sonnet 5.5 | scan | 100% | 95.5% | 99.8% | 60% | 2.6% | 0.0131 | 4.3 |
| Opus 5.5 | digital | 100% | 92.3% | 100.0% | 48% | 1.2% | 0.0262 | 6.0 |
| Opus 5.5 | scan | 100% | 95.5% | 99.8% | 60% | 3.5% | 0.0263 | 5.9 |

Cost of the run: $1.95 (150 calls).

**What went wrong, and it was not the models.** All three models failed on the same fields,
and digital PDFs scored *worse* than scans: a sign of a pipeline problem, not a reading one.
73 of the ~100 wrong fields were a missing supplier/buyer VAT number (and some names) on
the `modern` template. Docling labels that template's coloured header band as a page header
("furniture") and our parser dropped that layer, so the issuer's address and VAT number never
reached the LLM. With the issuer missing, the models sometimes assigned the remaining
company to the wrong role on purchase orders. Other errors: OCR `plc` -> `ple` copied
as-is, and one model wrote the string `"null"` for an empty cell, because the v1 prompt said
"use null" while the schema uses empty strings.

**Fixes (parse-v2, extract-v2).**
- Parser keeps Docling's furniture layer (page headers/footers). Regression test added.
- Prompt v2: empty string for absent values, never "null"; issuer details often sit in a
  header or footer. v1 is kept unchanged so these results stay reproducible.
- LLM cache key now includes the hash of the text sent, not only the file hash: otherwise
  a parser change would have silently served stale v1 answers for the same file.

**Takeaways so far.** Document type: 100% for every model. Line items: ≥99.5% even on scans.
Sonnet matched Opus at half the price; Haiku was close at ~1/37 of Opus's cost. Final model
choice waits for the v2 run.

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
