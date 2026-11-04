/** Findings inbox logic: rule descriptions, filtering and money totals. Pure, so tested. */

type FindingLike = { rule: string; type: string; status: string; amount_impact?: string | null };

/** What each deterministic rule checks (ADR-0002), shown as a tooltip. */
export const RULES: Record<string, string> = {
  R1: "Invoiced quantity is more than was delivered and not yet invoiced",
  R2: "Invoiced unit price differs from the purchase order",
  R3: "Line total is not quantity × unit price",
  R4: "Line VAT does not match the VAT rate",
  R5: "Net total is not the sum of the lines",
  R6: "VAT total is not the sum of the line VAT",
  R7: "Gross total is not net + VAT",
  R8: "The same invoice was received twice",
  M1: "No matching purchase order or delivery note",
};

export const TYPE_GROUPS = [
  { key: "matching", label: "Matching", types: ["quantity_mismatch", "unit_price_mismatch", "unmatched_document"] },
  { key: "arithmetic", label: "Arithmetic", types: ["line_total_error", "vat_error", "total_error"] },
  { key: "duplicate", label: "Duplicates", types: ["duplicate_invoice"] },
] as const;
export type GroupKey = "all" | (typeof TYPE_GROUPS)[number]["key"];

export function inGroup(finding: FindingLike, group: GroupKey): boolean {
  if (group === "all") return true;
  const g = TYPE_GROUPS.find((t) => t.key === group);
  return !!g && (g.types as readonly string[]).includes(finding.type);
}

const SCALE = 4; // API amounts have at most 4 decimal places

function toUnits(decimal: string): bigint {
  const negative = decimal.trim().startsWith("-");
  const [whole, frac = ""] = decimal.trim().replace(/^[-+]/, "").split(".");
  const units = BigInt(whole || "0") * 10n ** BigInt(SCALE) + BigInt((frac + "0".repeat(SCALE)).slice(0, SCALE));
  return negative ? -units : units;
}

function fromUnits(units: bigint, places = 2): string {
  const negative = units < 0n;
  const abs = negative ? -units : units;
  const base = 10n ** BigInt(SCALE);
  const text = `${abs / base}.${(abs % base).toString().padStart(SCALE, "0").slice(0, places)}`;
  return negative ? `-${text}` : text;
}

/**
 * Money at risk: the sum of |amount impact|, exact (BigInt, no floats). An overcharge and an
 * undercharge both need attention, so they add up instead of cancelling out.
 */
export function moneyAtRisk(findings: FindingLike[]): string {
  let total = 0n;
  for (const f of findings) {
    if (!f.amount_impact) continue;
    const units = toUnits(f.amount_impact);
    total += units < 0n ? -units : units;
  }
  return fromUnits(total);
}

export function countByStatus(findings: FindingLike[]): Record<"open" | "resolved" | "dismissed", number> {
  const out = { open: 0, resolved: 0, dismissed: 0 };
  for (const f of findings) if (f.status in out) out[f.status as keyof typeof out] += 1;
  return out;
}
