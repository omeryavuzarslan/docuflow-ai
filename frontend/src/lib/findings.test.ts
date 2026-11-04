import { describe, expect, it } from "vitest";
import { countByStatus, inGroup, moneyAtRisk, RULES } from "./findings";

const f = (type: string, amount_impact: string | null, status = "open") => ({ rule: "R1", type, status, amount_impact });

describe("moneyAtRisk", () => {
  it("adds absolute impacts exactly", () => {
    // 0.1 + 0.2 in floats is 0.30000000000000004; here it must be exact.
    expect(moneyAtRisk([f("a", "0.10"), f("b", "0.20")])).toBe("0.30");
    // An undercharge still needs attention: -15.50 counts as 15.50.
    expect(moneyAtRisk([f("a", "5.29"), f("b", "-15.50"), f("c", null)])).toBe("20.79");
    expect(moneyAtRisk([])).toBe("0.00");
  });

  it("handles large amounts and four decimal places", () => {
    expect(moneyAtRisk([f("a", "9999999999.9999"), f("b", "0.0001")])).toBe("10000000000.00");
  });
});

describe("filters", () => {
  it("groups finding types", () => {
    expect(inGroup(f("vat_error", null), "arithmetic")).toBe(true);
    expect(inGroup(f("vat_error", null), "matching")).toBe(false);
    expect(inGroup(f("duplicate_invoice", null), "all")).toBe(true);
  });

  it("counts by status", () => {
    expect(countByStatus([f("a", null), f("b", null, "dismissed"), f("c", null, "open")])).toEqual({
      open: 2,
      resolved: 0,
      dismissed: 1,
    });
  });

  it("describes every rule the backend has", () => {
    expect(Object.keys(RULES).sort()).toEqual(["M1", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]);
  });
});
