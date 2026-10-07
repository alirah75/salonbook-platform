export type Totals = {
  received: string;
  refunded: string;
  net: string;
  allocated_received: string;
  allocated_refunded: string;
  revenue: string;
  unallocated_net: string;
};
export type Daily = Totals & { day: string };
export type FinancialReport = {
  start: string;
  end: string;
  timezone: string;
  is_test: boolean;
  generated_at: string;
  totals: Totals;
  daily: Daily[];
};
export type Breakdown = {
  id: string;
  name: string;
  received: string;
  refunded: string;
  net: string;
};
export type FinancialDocument = {
  id: string;
  appointment_id: string;
  line_id: string;
  number: string | null;
  at: string;
  amount: string;
  status: string;
  allocated: boolean | null;
  refundable: string | null;
  reason: string | null;
};
export type InvoiceDocument = {
  id: string;
  number: string;
  amount: string;
  is_test: boolean;
  issued_at: string;
  seller: string;
  buyer: string;
  items: { description: string; amount: string }[];
};
// Report aggregates may exceed Number.MAX_SAFE_INTEGER. Never coerce money to Number.
export const rials = (amount: string) =>
  `${new Intl.NumberFormat("fa-IR").format(BigInt(amount))} ریال`;
export function monthRange(day: string): [string, string] {
  const [year, month] = day.split("-").map(Number);
  return [
    `${year}-${String(month).padStart(2, "0")}-01`,
    new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10),
  ];
}
export function validRange(start: string, end: string): boolean {
  const days = (Date.parse(end) - Date.parse(start)) / 86400000;
  return (
    start >= "2000-01-01" && end <= "2100-12-31" && days >= 0 && days < 366
  );
}
export function chartPercent(amount: string, maximum: bigint): number {
  return maximum > BigInt(0)
    ? Number((BigInt(amount) * BigInt(10000)) / maximum) / 100
    : 0;
}
export const refundStatuses: Record<string, string> = {
  REQUESTED: "در انتظار تأیید",
  APPROVED: "تأیید شده",
  PROCESSING: "در حال بازپرداخت",
  RECONCILIATION_REQUIRED: "در حال بررسی",
  SUCCEEDED: "موفق",
  FAILED: "ناموفق",
  CANCELLED: "لغو شده",
  ISSUED: "صادر شده",
};
