# ADR-0001: VAT is calculated and rounded per line

- Status: accepted
- Date: 2026-11-01

## Context

Pence cannot be split, so every computed amount has to be rounded. Two choices matter:

1. **Rounding mode.** Python's `Decimal` defaults to banker's rounding (round half to even:
   0.125 -> 0.12). Invoices conventionally round halves up (0.125 -> 0.13).
2. **Where VAT is rounded.** Per line (round each line's VAT, then sum) or per invoice (sum
   the nets, then compute and round VAT once). The two can differ by a few pence: three
   lines of 0.025 net at 20% give 0.03 per line but 0.02 per invoice (tested in
   `test_calculations.py`).

HMRC accepts more than one method, including line-level calculation and rounding the
invoice-level VAT total down to the whole penny (VAT Notice 700, section 17). Real
suppliers therefore do not all agree to the penny.

## Decision

- All arithmetic uses `Decimal`; floats are rejected by the domain types.
- Rounding is always `quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`, in one function,
  `calculations.round_money`.
- Rounding happens only at defined points: line net (quantity x unit price) and line VAT
  (line net x rate). Totals are sums of already-rounded line values. Nothing is rounded twice.
  Unit prices and quantities keep 4 decimal places.
- The synthetic data generator uses this single method, so clean documents are exact.

## Consequences

- Ground truth is unambiguous: a clean synthetic invoice matches our calculation exactly.
- The rule engine (roadmap step 4) must **not** assume suppliers use our method. The VAT and
  total rules will accept an amount that matches any HMRC-permitted method, otherwise
  correctly prepared real invoices would be flagged (false positives). The exact permitted
  methods are to be confirmed against current GOV.UK guidance at that step.
- We never round a value read from a document. Rounding applies only to values we compute.
