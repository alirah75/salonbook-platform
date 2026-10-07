import type { Appointment, Page } from "./booking";
export type Grant = {
  permission: string;
  scope: string;
  line_id: string | null;
};
export type Workspace = {
  salon_name: string;
  timezone: string;
  today: string;
  grants: Grant[];
  roles: string[];
  employee_id: string | null;
  lines: { id: string; name: string }[];
};
export const can = (w: Workspace, permission: string, line?: string | null) =>
  w.grants.some(
    (g) =>
      g.permission === permission &&
      (g.scope === "TENANT" ||
        (!!line && g.scope === "LINE" && g.line_id === line)),
  );
export const has = (w: Workspace, ...permissions: string[]) =>
  w.grants.some((g) => permissions.includes(g.permission));
export const sections = [
  { id: "", label: "نمای کلی", permissions: [] },
  {
    id: "appointments",
    label: "نوبت‌های کاری",
    permissions: ["appointment.read", "appointment.read_assigned"],
  },
  { id: "catalog", label: "لاین‌ها و خدمات", permissions: ["catalog.manage"] },
  {
    id: "team",
    label: "تیم و مهارت‌ها",
    permissions: ["staff.assign", "staff.manage"],
  },
  {
    id: "schedule",
    label: "برنامه و مرخصی",
    permissions: ["schedule.read", "schedule.read_own"],
  },
  { id: "users", label: "حساب‌های سالن", permissions: ["users.read"] },
  { id: "roles", label: "نقش‌ها و دسترسی", permissions: ["roles.read"] },
  { id: "finance", label: "گزارش مالی", permissions: ["finance.read"] },
  { id: "settings", label: "تنظیمات سالن", permissions: ["salon.manage"] },
] as const;
export const visibleSections = (w: Workspace) =>
  sections.filter(
    (s) =>
      s.permissions.length === 0 ||
      (["users", "roles", "settings"].includes(s.id)
        ? s.permissions.some((p) => can(w, p))
        : has(w, ...s.permissions)),
  );
export type WorkAppointment = Appointment & { customer_name: string };
export type Overview = {
  day: string;
  timezone: string;
  generated_at: string;
  counts: Record<string, number>;
  appointments: Page<WorkAppointment>;
};
export type Line = {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
};
export type CatalogService = {
  id: string;
  name: string;
  code: string;
  description: string | null;
  is_active: boolean;
};
export type LineOffer = {
  id: string;
  service_id: string;
  service_name: string;
  price_amount: number;
  duration_minutes: number;
  buffer_before_minutes: number;
  buffer_after_minutes: number;
  is_active: boolean;
  is_free: boolean;
  effective_active: boolean;
};
export type ManagedUser = {
  id: string;
  display_name: string;
  phone: string | null;
  is_active: boolean;
  employee: { id: string; public_name: string; is_active: boolean } | null;
  assignments: {
    id: string;
    role_id: string;
    code: string;
    scope: string;
    line_id: string | null;
  }[];
};
export type Role = {
  id: string;
  code: string;
  name: string;
  permissions: string[];
  is_system: boolean;
};
export type Calendar = {
  id: string;
  scope: string;
  employee_id: string | null;
  line_id: string | null;
  employee_name: string | null;
  line_name: string | null;
};
export type Weekly = {
  weekday: number;
  kind: "OPEN" | "BREAK";
  start_minute: number;
  end_minute: number;
  valid_from: string;
  valid_until: string | null;
};
export type Block = {
  id: string;
  kind: string;
  status: string;
  starts_at: string;
  ends_at: string;
  reason: string | null;
};
export const roleNames: Record<string, string> = {
  salon_manager: "مدیر سالن",
  line_manager: "مدیر لاین",
  employee: "کارمند",
  customer: "مشتری",
};
export const calendarScopes: Record<string, string> = {
  SALON: "کل سالن",
  LINE: "لاین",
  EMPLOYEE: "کارمند",
  EMPLOYEE_LINE: "کارمند در لاین",
};
export const blockStatuses: Record<string, string> = {
  REQUESTED: "در انتظار تأیید",
  APPROVED: "تأیید شده",
  REJECTED: "رد شده",
  CANCELLED: "لغو شده",
};
export const permissionNames: Record<string, string> = {
  "profile.read": "دیدن حساب شخصی",
  "profile.update": "ویرایش حساب شخصی",
  "salon.read": "دیدن اطلاعات سالن",
  "salon.manage": "ویرایش سالن",
  "session.manage": "مدیریت ورودهای خود",
  "users.read": "دیدن حساب‌ها",
  "users.manage": "مدیریت حساب‌ها",
  "roles.read": "دیدن نقش‌ها",
  "roles.manage": "مدیریت دسترسی‌ها",
  "catalog.manage": "مدیریت خدمات",
  "staff.assign": "تخصیص تیم و مهارت",
  "staff.manage": "مدیریت کارکنان",
  "schedule.read": "دیدن برنامه",
  "schedule.manage": "ویرایش برنامه",
  "schedule.read_own": "دیدن برنامهٔ خود",
  "leave.request_own": "درخواست مرخصی خود",
  "appointment.create": "رزرو نوبت شخصی",
  "appointment.read": "دیدن نوبت‌های کاری",
  "appointment.read_own": "دیدن نوبت‌های شخصی",
  "appointment.read_assigned": "دیدن نوبت‌های محول‌شده",
  "appointment.cancel_own": "لغو نوبت شخصی",
  "appointment.reschedule_own": "جابجایی نوبت شخصی",
  "appointment.manage": "مدیریت نوبت‌ها",
  "appointment.finish_assigned": "ثبت نتیجهٔ نوبت محول‌شده",
  "appointment.override": "استثنای مهلت لغو",
  "finance.read": "دیدن مبالغ",
  "payment.refund": "درخواست بازپرداخت",
  "audit.read": "دیدن رویدادها",
};
export const minuteLabel = (minute: number) =>
  `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
export const minuteValue = (value: string) => {
  const [h, m] = value.split(":").map(Number);
  return h * 60 + m;
};
// Interpret a datetime-local input in the SALON zone, independent of the device zone.
export function zonedInstant(value: string, zone: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))
    throw new Error("Invalid date");
  const wanted = Date.parse(`${value}:00Z`);
  let instant = wanted;
  const format = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const local = (at: number) => {
    const p = Object.fromEntries(
      format.formatToParts(at).map((v) => [v.type, v.value]),
    );
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
  };
  for (let i = 0; i < 3; i++)
    instant += wanted - Date.parse(`${local(instant)}:00Z`);
  if (local(instant) !== value) throw new Error("Invalid local time");
  return new Date(instant).toISOString();
}
