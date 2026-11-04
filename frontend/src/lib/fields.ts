/**
 * Turns an extraction (raw values as printed, provenance, conversion errors) and the human
 * corrections into the rows the review screen shows. Pure functions, so they are unit-tested.
 *
 * Field paths are the backend's correction paths: "document_number", "supplier.vat_number",
 * "lines[2].quantity".
 */

export type Box = { left: number; top: number; right: number; bottom: number };
export type Location = { page: number; bbox: Box };

export type FieldView = {
  path: string;
  label: string;
  value: string; // what is shown: the latest correction, else the raw value
  raw: string; // what the model extracted
  corrected: boolean;
  location: Location | null; // where on the PDF the value was found
  // "unverified": the model returned a value we could not find on the page.
  // "error": the value could not be converted (e.g. not a valid date or amount).
  issue: { kind: "unverified" | "error"; message: string } | null;
};

export type LineView = { index: number; cells: Record<string, FieldView> };

export type FieldSections = {
  header: FieldView[];
  supplier: FieldView[];
  buyer: FieldView[];
  lines: LineView[];
  totals: FieldView[];
};

type Raw = Record<string, unknown>;
type Correction = { field: string; new_value: string };

const HEADER: [string, string][] = [
  ["document_number", "Number"],
  ["po_reference", "PO reference"],
  ["issue_date", "Issue date"],
  ["due_date", "Due date"],
  ["currency", "Currency"],
];
const PARTY: [string, string][] = [
  ["name", "Name"],
  ["vat_number", "VAT number"],
  ["address_line1", "Address"],
  ["address_line2", "Address line 2"],
  ["city", "City"],
  ["postcode", "Postcode"],
];
// Only these party fields are looked up on the page (see backend provenance.locate).
const LOCATED_PARTY = new Set(["name", "vat_number"]);
export const LINE_COLUMNS: [string, string][] = [
  ["sku", "SKU"],
  ["description", "Description"],
  ["quantity", "Qty"],
  ["unit_price", "Unit price"],
  ["vat_rate", "VAT"],
  ["line_net", "Net"],
  ["line_vat", "VAT amount"],
];
const TOTALS: [string, string][] = [
  ["net_total", "Net total"],
  ["vat_total", "VAT total"],
  ["gross_total", "Gross total"],
];

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** "lines[2].quantity: not a number" -> {"lines[2].quantity": "not a number"} */
export function errorsByPath(errors: string[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const error of errors) {
    const at = error.indexOf(": ");
    if (at > 0) out.set(error.slice(0, at), error.slice(at + 2));
  }
  return out;
}

export function buildFields(
  raw: Raw,
  provenance: Record<string, unknown>,
  conversionErrors: string[],
  corrections: Correction[],
): FieldSections {
  const latest = new Map<string, string>();
  for (const c of corrections) latest.set(c.field, c.new_value); // in order: last wins
  const errors = errorsByPath(conversionErrors);

  const field = (path: string, label: string, rawValue: string, located: boolean): FieldView => {
    const corrected = latest.has(path);
    const value = corrected ? (latest.get(path) as string) : rawValue;
    const where = provenance[path] as Location | null | undefined;
    let issue: FieldView["issue"] = null;
    const error = errors.get(path);
    if (error && !corrected) issue = { kind: "error", message: error };
    else if (located && rawValue && where === null && !corrected)
      issue = { kind: "unverified", message: "Not found on the page: check this value" };
    return {
      path,
      label,
      value,
      raw: rawValue,
      corrected,
      location: where ?? null,
      issue,
    };
  };

  const party = (role: "supplier" | "buyer") => {
    const data = (raw[role] ?? {}) as Raw;
    return PARTY.map(([key, label]) =>
      field(`${role}.${key}`, label, asText(data[key]), LOCATED_PARTY.has(key)),
    );
  };

  const header = HEADER.map(([key, label]) => field(key, label, asText(raw[key]), true));
  const refs = Array.isArray(raw.delivery_note_references) ? raw.delivery_note_references : [];
  refs.forEach((ref, i) =>
    header.push(
      field(
        `delivery_note_references[${i}]`,
        refs.length > 1 ? `Delivery note ${i + 1}` : "Delivery note",
        asText(ref),
        true,
      ),
    ),
  );

  const rawLines = Array.isArray(raw.lines) ? (raw.lines as Raw[]) : [];
  const lines = rawLines.map((line, index) => ({
    index,
    cells: Object.fromEntries(
      LINE_COLUMNS.map(([key, label]) => [
        key,
        field(`lines[${index}].${key}`, label, asText(line[key]), true),
      ]),
    ),
  }));

  return {
    header,
    supplier: party("supplier"),
    buyer: party("buyer"),
    lines,
    totals: TOTALS.map(([key, label]) => field(key, label, asText(raw[key]), true)),
  };
}

/** Every field, in display order: for counting issues. */
export function allFields(sections: FieldSections): FieldView[] {
  return [
    ...sections.header,
    ...sections.supplier,
    ...sections.buyer,
    ...sections.lines.flatMap((l) => Object.values(l.cells)),
    ...sections.totals,
  ];
}

/** Map a finding's domain field ("lines[1].quantity", "gross_total") to an extraction path. */
export function findingPath(field: string | null): string | null {
  if (!field) return null;
  return field
    .replace(/^po_number$/, "po_reference") // on an invoice: the PO it points to
    .replace(/^invoice_number$|^delivery_note_number$/, "document_number")
    .replace(/^delivery_note_numbers/, "delivery_note_references");
}

/** A box in PDF points -> CSS pixels on a page rendered at `scale` (pixels per point). */
export function toScreen(bbox: Box, scale: number, pad = 3) {
  return {
    left: bbox.left * scale - pad,
    top: bbox.top * scale - pad,
    width: (bbox.right - bbox.left) * scale + 2 * pad,
    height: (bbox.bottom - bbox.top) * scale + 2 * pad,
  };
}
