# ADR-0002: Discrepancy rules, tolerances and known limits

- Status: accepted
- Date: 2026-11-02

## Context

The rule engine decides whether an invoice disagrees with its purchase order and delivery
notes, or with itself. Two failure modes cost money: missing a real overcharge, and flagging
a correct invoice (a false positive teaches people to ignore the tool). Suppliers round
legitimately in different ways (ADR-0001), so exact equality would produce false positives.

HMRC VAT Notice 700, section 17.5 (checked 2026-11-02 on GOV.UK): VAT calculated per line may
be rounded to the nearest penny (or 0.5p) or down; the method must be consistent; the total
VAT may be rounded down to a whole penny.

## Decision

All arithmetic is Decimal. One rule, one place (`backend/app/validation/rules.py`):

| Rule | Accepts | Flags |
|---|---|---|
| R1 quantity | invoiced ≤ delivered − already invoiced (summed over all DNs of the PO) | invoiced more |
| R2 price | invoice unit price = PO unit price, exactly | any difference |
| R3 line net | \|line net − qty × price\| < £0.01 (nearest or truncated) | ≥ 1p off |
| R4 line VAT | nearest or rounded down, on the printed net or on the correct net | anything else |
| R5 VAT total | Σ printed line VAT; Σ line VAT (nearest or down); per-rate invoice-level (nearest or down) | anything else |
| R6 net total | Σ printed line nets, or Σ correct line nets | anything else |
| R7 gross | net total + VAT total, exactly | anything else |
| R8 duplicate | — | same supplier VAT number and invoice number as an earlier invoice |
| M1 matching | DN/invoice with PO number + supplier VAT number of a known PO | no matching PO |

Report each problem once, where it starts: R6 stays silent if the total matches the correct
line amounts (the line is at fault, R3), R4/R5 accept VAT computed on the correct net, and a
duplicate invoice is reported by R8 only.

Partial delivery (DN below PO) is not an error. Invoicing more than was delivered is.

SKUs are compared on letters and digits only (`CL.-2005` = `CL-2005`), because OCR adds
punctuation noise and a broken line match would look like an undelivered item.

No judgement on missing evidence: when a document could not be fully extracted and is with
a reviewer, checks that depend on it are *held*, not run. An invoice whose PO is under review
is not "unmatched"; an order with a delivery note under review gets no quantity check (R1).
Arithmetic checks on the invoice itself still run. Without this, one unreadable scan caused
three false alarms on other documents (measured, see docs/experiments.md).

The system flags; people decide. Nothing is paid or rejected automatically.

## Consequences and known limits

- Differences under 1p in line nets, and VAT rounded either permitted way, are never flagged
  (deliberate: they are not errors under HMRC rules). The generator injects ≥ 50p errors.
- R2 is exact: agreed price changes or discounts not on the PO are flagged. The planned
  supplier-contract rule (advanced stage) will supply agreed prices.
- Lines are matched by SKU; real suppliers may use their own codes (needs a mapping table).
  Two different SKUs that differ only in punctuation would be treated as one.
- R8 needs an exact (whitespace/case-insensitive) invoice number; `INV-001` vs `INV001` is
  missed. Fuzzy duplicate detection is future work.
- Not handled in v1: credit notes, non-GBP currency, discount/shipping lines, mixed-method
  (0.5p) line rounding.
- Documents whose extraction failed conversion are not checked; they go to human review.
