import { z } from "zod";

export type Page<T> = {
  items: T[];
  has_more: boolean;
  limit: number;
  offset: number;
};
export type Service = { id: string; name: string; description: string | null };
export type Offer = {
  line_id: string;
  line_name: string;
  service_id: string;
  price_amount: number;
  duration_minutes: number;
  is_free: boolean;
};
export type Employee = { id: string; public_name: string };
export type Settings = {
  timezone: string;
  today: string;
  booking_horizon_days: number;
  cancel_before_minutes: number;
};
export type Slot = {
  employee_id: string;
  employee_name: string;
  starts_at: string;
  ends_at: string;
};
export type Availability = Page<Slot> & {
  timezone: string;
  total_amount: number;
  duration_minutes: number;
  generated_at: string;
};
export type Appointment = {
  id: string;
  status: string;
  employee_name: string;
  employee_id: string;
  line_id: string;
  starts_at: string;
  ends_at: string;
  total_amount: number | null;
  duration_minutes: number;
  is_test: boolean;
  hold_expires_at: string | null;
  version: number;
  cancellation_reason: string | null;
  items: {
    service_id: string;
    service_name: string;
    line_name: string;
    amount: number | null;
  }[];
};
export type Payment = {
  id: string;
  appointment_id: string;
  appointment_status: string;
  status: string;
  amount: number;
  is_test: boolean;
  expires_at: string;
  checkout_path: string | null;
  transactions: {
    id: string;
    amount: number;
    allocated: boolean;
    receipt_number: string;
    refunds: { id: string; amount: number; status: string }[];
  }[];
};
export const uuidPattern =
  "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
export function safeReturn(value: unknown): string {
  return typeof value === "string" &&
    new RegExp(
      `^/(booking|dashboard(?:/(appointments|catalog|team|schedule|users|roles|settings|finance))?|appointments(?:/${uuidPattern})?|payments/${uuidPattern}(?:/result)?)$`,
    ).test(value)
    ? value
    : "/account";
}
export const loginUrl = (path: string) =>
  `/login?returnTo=${encodeURIComponent(safeReturn(path))}`;
export function money(amount: number | null): string {
  if (amount === null) return "مبلغ در دسترس نیست";
  if (!Number.isSafeInteger(amount) || amount < 0)
    return "برای اطلاع از مبلغ با سالن تماس بگیرید";
  return amount === 0
    ? "رایگان"
    : `${new Intl.NumberFormat("fa-IR").format(amount)} ریال`;
}
export const number = (value: number) =>
  new Intl.NumberFormat("fa-IR").format(value);
export function dateLabel(
  value: string,
  zone: string,
  withTime = false,
): string {
  return new Intl.DateTimeFormat("fa-IR", {
    timeZone: value.length === 10 ? "UTC" : zone,
    weekday: "long",
    month: "long",
    day: "numeric",
    ...(withTime ? ({ hour: "2-digit", minute: "2-digit" } as const) : {}),
  }).format(new Date(value.length === 10 ? `${value}T12:00:00Z` : value));
}
export const timeLabel = (value: string, zone: string) =>
  new Intl.DateTimeFormat("fa-IR", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
export const addDays = (day: string, count: number) =>
  new Date(Date.parse(`${day}T12:00:00Z`) + count * 86400000)
    .toISOString()
    .slice(0, 10);
export const statuses: Record<string, string> = {
  AWAITING_PAYMENT: "در انتظار پرداخت",
  CONFIRMED: "تأیید شده",
  CANCELLED: "لغو شده",
  EXPIRED: "مهلت تمام شده",
  COMPLETED: "انجام شده",
  NO_SHOW: "عدم حضور",
  CREATED: "در حال آماده‌سازی",
  PENDING: "در انتظار نتیجه",
  VERIFYING: "در حال بررسی",
  SUCCEEDED: "موفق",
  FAILED: "ناموفق",
  RECONCILIATION_REQUIRED: "در حال بررسی نتیجه",
  REQUESTED: "درخواست شده",
  APPROVED: "در انتظار بازگشت",
  PROCESSING: "در حال بازگشت",
};
export const paymentOpen = (status: string) =>
  ["CREATED", "PENDING", "VERIFYING", "RECONCILIATION_REQUIRED"].includes(
    status,
  );
export function paymentConfirmed(payment: Payment): boolean {
  return (
    ["CONFIRMED", "COMPLETED", "NO_SHOW"].includes(
      payment.appointment_status,
    ) && payment.transactions.some((transaction) => transaction.allocated)
  );
}

const draftSchema = z.object({
  version: z.literal(1),
  intent: z.uuid().optional(),
  step: z.number().int().min(1).max(6),
  service: z
    .object({
      id: z.uuid(),
      name: z.string().max(160),
      description: z.string().max(4000).nullable(),
    })
    .optional(),
  offer: z
    .object({
      line_id: z.uuid(),
      line_name: z.string().max(120),
      service_id: z.uuid(),
      price_amount: z.number().int().nonnegative(),
      duration_minutes: z.number().int().positive(),
      is_free: z.boolean(),
    })
    .optional(),
  employee: z
    .object({
      id: z.union([z.uuid(), z.literal("auto")]),
      public_name: z.string().max(160),
    })
    .optional(),
  day: z.iso.date().optional(),
  slot: z
    .object({
      employee_id: z.uuid(),
      employee_name: z.string().max(160),
      starts_at: z.iso.datetime({ offset: true }),
      ends_at: z.iso.datetime({ offset: true }),
    })
    .optional(),
});
export type Draft = z.infer<typeof draftSchema>;
export const emptyDraft: Draft = { version: 1, step: 1 };
export function parseDraft(raw: string | null): Draft {
  try {
    const d = draftSchema.parse(JSON.parse(raw ?? "null"));
    if (
      (d.step > 1 && !d.service) ||
      (d.step > 2 && (!d.offer || d.offer.service_id !== d.service?.id)) ||
      (d.step > 3 && !d.employee) ||
      (d.step > 4 && !d.day) ||
      (d.step > 5 && !d.slot)
    )
      return emptyDraft;
    return d;
  } catch {
    return emptyDraft;
  }
}
const memory = new Map<string, string>();
export function readStorage(key: string): string | null {
  try {
    return (
      sessionStorage.getItem(`salonbook:${key}`) ?? memory.get(key) ?? null
    );
  } catch {
    return memory.get(key) ?? null;
  }
}
export function saveStorage(key: string, value: string) {
  memory.set(key, value);
  try {
    sessionStorage.setItem(`salonbook:${key}`, value);
  } catch {
    /* The current page still retains the replay key. */
  }
}
// Keep the same key after an ambiguous response, including reload. Only an explicit
// new operation (new payload or reviewed terminal payment attempt) gets a new key.
export function mutationKey(
  userId: string,
  operation: string,
  payload: unknown,
): string {
  const name = `operation:${userId}:${operation}`;
  const fingerprint = JSON.stringify(payload);
  try {
    const old = JSON.parse(readStorage(name) ?? "null");
    if (old?.fingerprint === fingerprint && z.uuid().safeParse(old.key).success)
      return old.key;
  } catch {
    /* Invalid browser state is replaced. */
  }
  const key = crypto.randomUUID();
  saveStorage(name, JSON.stringify({ fingerprint, key }));
  return key;
}
