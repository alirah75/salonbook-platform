import { describe, expect, it } from "vitest";
import { chartPercent, monthRange, rials, validRange } from "@/lib/finance";
import { safeReturn } from "@/lib/booking";

describe("financial reports", () => {
  it("preserves exact rial values beyond the browser integer limit", () => {
    expect(rials("9007199254740993")).toContain("۹٬۰۰۷٬۱۹۹٬۲۵۴٬۷۴۰٬۹۹۳");
    expect(rials("-1")).toContain("۱");
    expect(rials("0")).toBe("۰ ریال");
    expect(chartPercent("9007199254740993", BigInt("18014398509481986"))).toBe(
      50,
    );
    expect(chartPercent("0", BigInt(0))).toBe(0);
  });
  it("uses full calendar months and inclusive bounded custom periods", () => {
    expect(monthRange("2024-02-12")).toEqual(["2024-02-01", "2024-02-29"]);
    expect(monthRange("2026-12-31")).toEqual(["2026-12-01", "2026-12-31"]);
    expect(validRange("2024-01-01", "2024-12-31")).toBe(true);
    expect(validRange("2024-01-01", "2025-01-01")).toBe(false);
    expect(validRange("2026-02-02", "2026-02-01")).toBe(false);
    expect(validRange("", "2026-02-01")).toBe(false);
    expect(safeReturn("/dashboard/finance")).toBe("/dashboard/finance");
  });
});
