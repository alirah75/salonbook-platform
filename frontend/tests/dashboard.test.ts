import { describe, expect, it } from "vitest";
import {
  can,
  visibleSections,
  zonedInstant,
  type Workspace,
} from "@/lib/dashboard";
import { safeReturn } from "@/lib/booking";
const base: Workspace = {
  salon_name: "Salon",
  timezone: "Asia/Tehran",
  today: "2026-10-05",
  roles: ["salon_manager"],
  grants: [],
  employee_id: null,
  lines: [],
};
describe("workspace permissions", () => {
  it("uses grants, never role labels, for navigation and line mutations", () => {
    expect(visibleSections(base).map((s) => s.id)).toEqual([""]);
    const scoped = {
      ...base,
      roles: ["custom_reception"],
      grants: [
        { permission: "catalog.manage", scope: "LINE", line_id: "hair" },
        { permission: "users.read", scope: "LINE", line_id: "hair" },
      ],
    };
    expect(can(scoped, "catalog.manage", "hair")).toBe(true);
    expect(can(scoped, "catalog.manage", "nails")).toBe(false);
    expect(can(scoped, "catalog.manage")).toBe(false);
    expect(visibleSections(scoped).map((s) => s.id)).toEqual(["", "catalog"]);
  });
  it("offers employees only their readable workspace areas", () => {
    const employee = {
      ...base,
      roles: ["employee", "customer"],
      grants: [
        {
          permission: "appointment.read_assigned",
          scope: "TENANT",
          line_id: null,
        },
        { permission: "schedule.read_own", scope: "TENANT", line_id: null },
      ],
    };
    expect(visibleSections(employee).map((s) => s.id)).toEqual([
      "",
      "appointments",
      "schedule",
    ]);
    expect(can(employee, "appointment.manage")).toBe(false);
  });
  it("interprets local input in salon time and rejects DST gaps", () => {
    expect(zonedInstant("2026-10-05T09:30", "Asia/Tehran")).toBe(
      "2026-10-05T06:00:00.000Z",
    );
    expect(() =>
      zonedInstant("2026-03-08T02:30", "America/New_York"),
    ).toThrow();
    expect(() => zonedInstant("2026-02-30T09:00", "Asia/Tehran")).toThrow();
  });
  it("keeps dashboard login return paths bounded", () => {
    expect(safeReturn("/dashboard/schedule")).toBe("/dashboard/schedule");
    expect(safeReturn("/dashboard/../platform")).toBe("/account");
    expect(safeReturn("/platform")).toBe("/account");
    expect(safeReturn("/dashboard?returnTo=https://evil.test")).toBe(
      "/account",
    );
  });
});
