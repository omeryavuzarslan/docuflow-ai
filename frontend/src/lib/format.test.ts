import { describe, expect, it } from "vitest";

import { docTypeLabel, formatMoney, formatRelative, shortName } from "./format";

describe("formatMoney", () => {
  it("groups thousands and keeps two decimals without float arithmetic", () => {
    expect(formatMoney("883.95")).toBe("£883.95");
    expect(formatMoney("5651.72")).toBe("£5,651.72");
    expect(formatMoney("1234567.5")).toBe("£1,234,567.50");
    expect(formatMoney("-15.50")).toBe("−£15.50");
  });
  it("shows a dash for missing values", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney("")).toBe("—");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-11-04T12:00:00Z");
  it.each([
    ["2026-11-04T11:59:40Z", "just now"],
    ["2026-11-04T11:30:00Z", "30 min ago"],
    ["2026-11-04T07:00:00Z", "5 h ago"],
    ["2026-11-01T12:00:00Z", "3 d ago"],
  ])("%s -> %s", (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected);
  });
});

describe("labels", () => {
  it("names document types, agreements included", () => {
    expect(docTypeLabel("purchase_order")).toBe("Purchase order");
    expect(docTypeLabel("other")).toBe("Agreement");
    expect(docTypeLabel(null)).toBe("Detecting…");
  });
  it("drops folders from file names", () => {
    expect(shortName("set-003/inv-1.pdf")).toBe("inv-1.pdf");
  });
});
