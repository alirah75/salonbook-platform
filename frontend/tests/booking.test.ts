import { describe, expect, it } from "vitest";
import {
  addDays,
  money,
  mutationKey,
  parseDraft,
  paymentConfirmed,
  safeReturn,
  type Payment,
} from "@/lib/booking";

describe("customer booking boundaries", () => {
  it("only accepts explicit local return routes", () => {
    expect(safeReturn("/booking")).toBe("/booking");
    expect(
      safeReturn("/appointments/12345678-1234-1234-1234-123456789012"),
    ).toContain("/appointments/");
    for (const value of [
      "//evil.test",
      "https://evil.test",
      "/booking?next=//evil.test",
      "/booking/../api",
      ["/booking"],
      undefined,
    ])
      expect(safeReturn(value)).toBe("/account");
  });
  it("rejects corrupt and incomplete saved selections", () => {
    expect(parseDraft("not-json").step).toBe(1);
    expect(parseDraft('{"version":1,"step":6}').step).toBe(1);
    expect(parseDraft('{"version":1,"step":1,"password":"secret"}')).toEqual({
      version: 1,
      step: 1,
    });
  });
  it("retains a key for a retried command and isolates users and new intents", () => {
    const operation = crypto.randomUUID();
    const key = mutationKey("customer-a", operation, { slot: "one" });
    expect(mutationKey("customer-a", operation, { slot: "one" })).toBe(key);
    expect(mutationKey("customer-b", operation, { slot: "one" })).not.toBe(key);
    expect(
      mutationKey("customer-a", operation + "-new", { slot: "one" }),
    ).not.toBe(key);
  });
  it("never describes a late or unmatched receipt as a confirmed booking", () => {
    const payment = {
      appointment_status: "EXPIRED",
      transactions: [{ allocated: false }],
    } as Payment;
    expect(paymentConfirmed(payment)).toBe(false);
    expect(
      paymentConfirmed({ ...payment, appointment_status: "CONFIRMED" }),
    ).toBe(false);
    expect(
      paymentConfirmed({
        ...payment,
        appointment_status: "CONFIRMED",
        transactions: [{ allocated: true }],
      } as Payment),
    ).toBe(true);
    expect(
      paymentConfirmed({
        ...payment,
        appointment_status: "CANCELLED",
        transactions: [{ allocated: true }],
      } as Payment),
    ).toBe(false);
  });
  it("does not round unsafe money and advances ISO days across year boundaries", () => {
    expect(money(0)).toBe("رایگان");
    expect(money(1_800_000)).toContain("ریال");
    expect(money(Number.MAX_SAFE_INTEGER + 1)).toContain("تماس");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });
});
