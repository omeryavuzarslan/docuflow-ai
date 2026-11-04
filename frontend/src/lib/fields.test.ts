import { describe, expect, it } from "vitest";
import { allFields, buildFields, errorsByPath, findingPath, toScreen } from "./fields";

const box = { left: 10, top: 20, right: 60, bottom: 30 };
const raw = {
  doc_type: "invoice",
  document_number: "INV-1",
  po_reference: "PO-1",
  issue_date: "12/02/2026",
  due_date: "",
  currency: "GBP",
  delivery_note_references: ["DN-1"],
  supplier: { name: "Kestrel Ltd", vat_number: "GB123", city: "Leeds" },
  buyer: { name: "Harbour plc", vat_number: "" },
  lines: [{ sku: "OF-1", quantity: "3", unit_price: "£16.95" }],
  net_total: "£50.85",
  vat_total: "£10.17",
  gross_total: "£61.O2", // OCR read a letter O
};

describe("buildFields", () => {
  it("shows raw values with their location on the page", () => {
    const s = buildFields(raw, { document_number: { page: 1, bbox: box } }, [], []);
    const number = s.header[0];
    expect(number).toMatchObject({ label: "Number", value: "INV-1", corrected: false });
    expect(number.location).toEqual({ page: 1, bbox: box });
    expect(number.issue).toBeNull();
    expect(s.header[s.header.length - 1]).toMatchObject({ path: "delivery_note_references[0]", value: "DN-1" });
    expect(s.lines[0].cells.quantity.path).toBe("lines[0].quantity");
  });

  it("flags a value the model returned but we could not find on the page", () => {
    const s = buildFields(raw, { "supplier.vat_number": null }, [], []);
    expect(s.supplier[1].issue?.kind).toBe("unverified");
    // An empty value, or a field we never look up (city), is not flagged.
    expect(s.header.find((f) => f.path === "due_date")?.issue).toBeNull();
    expect(s.supplier.find((f) => f.path === "supplier.city")?.issue).toBeNull();
  });

  it("flags conversion errors and clears them once corrected", () => {
    const errors = ["gross_total: not a valid amount"];
    const before = buildFields(raw, {}, errors, []);
    expect(before.totals[2].issue).toEqual({ kind: "error", message: "not a valid amount" });

    const after = buildFields(raw, {}, errors, [
      { field: "gross_total", new_value: "£61.00" },
      { field: "gross_total", new_value: "£61.02" }, // the latest correction wins
    ]);
    expect(after.totals[2]).toMatchObject({
      value: "£61.02",
      raw: "£61.O2",
      corrected: true,
      issue: null,
    });
  });

  it("lists every field once for counting", () => {
    const s = buildFields(raw, {}, [], []);
    const paths = allFields(s).map((f) => f.path);
    expect(new Set(paths).size).toBe(paths.length);
    expect(paths).toContain("lines[0].line_vat");
  });
});

describe("helpers", () => {
  it("splits conversion errors by path", () => {
    expect(errorsByPath(["lines[1].quantity: missing", "junk"])).toEqual(
      new Map([["lines[1].quantity", "missing"]]),
    );
  });

  it("maps finding fields to extraction paths", () => {
    expect(findingPath("lines[1].quantity")).toBe("lines[1].quantity");
    expect(findingPath("po_number")).toBe("po_reference");
    expect(findingPath(null)).toBeNull();
  });
});

describe("toScreen", () => {
  it("scales PDF points to pixels with padding", () => {
    expect(toScreen(box, 2, 3)).toEqual({ left: 17, top: 37, width: 106, height: 26 });
  });
});
