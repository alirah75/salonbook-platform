"use client";
import { useState } from "react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Wallet,
  ChartNoAxesCombined,
} from "lucide-react";
import { dateLabel, mutationKey, saveStorage, type Page } from "@/lib/booking";
import { api } from "@/lib/api";
import { useAuth } from "../auth-provider";
import { can } from "@/lib/dashboard";
import {
  chartPercent,
  monthRange,
  refundStatuses,
  rials,
  validRange,
  type Breakdown,
  type Daily,
  type FinancialDocument,
  type FinancialReport,
  type InvoiceDocument,
} from "@/lib/finance";
import { useResource, Pager } from "../booking/resource";
import { Field } from "../ui";
import {
  ActionForm,
  Check,
  Empty,
  Panel,
  ResourceState,
  Select,
  useWorkspace,
  useWrite,
  value,
} from "./shared";

export function FinancePanel() {
  const { workspace } = useWorkspace();
  const [mode, setMode] = useState("day");
  const [anchor, setAnchor] = useState(workspace.today);
  const [customStart, setStart] = useState(workspace.today);
  const [customEnd, setEnd] = useState(workspace.today);
  const [line, setLine] = useState("");
  const [test, setTest] = useState("true");
  const [revision, setRevision] = useState(0);
  const [start, end] =
    mode === "month"
      ? monthRange(anchor)
      : mode === "day"
        ? [anchor, anchor]
        : [customStart, customEnd];
  const valid = validRange(start, end);
  const query = new URLSearchParams({
    start,
    end,
    is_test: test,
    ...(line ? { line_id: line } : {}),
  }).toString();
  // Remount all reports when filters change: never label an old result with a new period.
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">اعداد روشن، تصمیم‌های بهتر</span>
        <h1>
          گزارش مالی<span className="accent-dot">.</span>
        </h1>
        <p>دریافت‌ها، بازپرداخت‌ها و درآمد خدمات در محدودهٔ دسترسی شما.</p>
      </div>
      <div className="work-filters finance-filters">
        <Select
          label="نوع گزارش"
          value={mode}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value="day">روزانه</option>
          <option value="month">ماهانه (میلادی)</option>
          <option value="custom">بازهٔ دلخواه</option>
        </Select>
        {mode === "custom" ? (
          <>
            <Field
              label="از تاریخ (میلادی)"
              type="date"
              min="2000-01-01"
              max="2100-12-31"
              required
              value={customStart}
              onChange={(e) => setStart(e.target.value)}
            />
            <Field
              label="تا تاریخ (میلادی)"
              type="date"
              min="2000-01-01"
              max="2100-12-31"
              required
              value={customEnd}
              onChange={(e) => setEnd(e.target.value)}
            />
          </>
        ) : (
          <Field
            label={
              mode === "day"
                ? "روز گزارش (میلادی)"
                : "یک روز از ماه موردنظر (میلادی)"
            }
            type="date"
            min="2000-01-01"
            max="2100-12-31"
            required
            value={anchor}
            onChange={(e) => {
              if (e.target.value) setAnchor(e.target.value);
            }}
          />
        )}
        <Select
          label="لاین گزارش"
          value={line}
          onChange={(e) => setLine(e.target.value)}
        >
          <option value="">همهٔ لاین‌های مجاز</option>
          {workspace.lines
            .filter((l) => can(workspace, "finance.read", l.id))
            .map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
        </Select>
        <Select
          label="نوع مبالغ"
          value={test}
          onChange={(e) => setTest(e.target.value)}
        >
          <option value="true">آزمایشی</option>
          <option value="false">واقعی</option>
        </Select>
        <button
          className="button secondary"
          onClick={() => setRevision((r) => r + 1)}
        >
          به‌روزرسانی گزارش
        </button>
      </div>
      <p className="finance-notice">
        {test === "true"
          ? "گزارش آزمایشی — این مبالغ جابه‌جایی پول واقعی نیستند."
          : "گزارش مبالغ واقعی — درگاه واقعی هنوز فعال نشده است."}
      </p>
      {!valid ? (
        <p className="form-error" role="alert">
          بازه‌ای معتبر، حداکثر ۳۶۶ روز، انتخاب کنید.
        </p>
      ) : (
        <FinancialResults
          key={query}
          query={query}
          revision={revision}
          refresh={() => setRevision((r) => r + 1)}
        />
      )}
    </>
  );
}

function FinancialResults({
  query,
  refresh,
  revision,
}: {
  query: string;
  refresh: () => void;
  revision: number;
}) {
  const report = useResource<FinancialReport>(
    `/finance/report?${query}`,
    0,
    api,
    revision,
  );
  return (
    <>
      <ResourceState resource={report} />
      {report.data && !report.error && (
        <>
          <p className="muted">
            {dateLabel(report.data.start, "UTC")} تا{" "}
            {dateLabel(report.data.end, "UTC")} · زمان سالن:{" "}
            <bdi>{report.data.timezone}</bdi>
          </p>
          <div className="work-metrics finance-metrics">
            {(
              [
                ["دریافت قطعی", report.data.totals.received, ArrowDownLeft],
                ["بازپرداخت قطعی", report.data.totals.refunded, ArrowUpRight],
                ["خالص جریان پول", report.data.totals.net, Wallet],
                [
                  "خالص دریافتی خدمات",
                  report.data.totals.revenue,
                  ChartNoAxesCombined,
                ],
              ] as const
            ).map(([label, amount, Icon]) => (
              <section key={label}>
                <Icon size={21} aria-hidden />
                <span>{label}</span>
                <strong>{rials(amount)}</strong>
              </section>
            ))}
          </div>
          <p className="muted">
            خالص مبالغ تخصیص‌نیافته به رزرو:{" "}
            <strong>{rials(report.data.totals.unallocated_net)}</strong>
          </p>
          <details className="finance-definition">
            <summary>این اعداد چگونه محاسبه می‌شوند؟</summary>
            <p>
              مبنای گزارش، زمان ثبت دریافت یا بازپرداخت قطعی به وقت سالن است؛
              روز پایان هم در بازه محاسبه می‌شود. پرداخت‌های ناموفق و در انتظار
              تأیید وارد جمع نمی‌شوند. این گزارش جریان پول است و سود یا دستمزد
              کارکنان را نشان نمی‌دهد.
            </p>
            <p>
              خالص دریافتی خدمات فقط مبالغ تخصیص‌یافته به رزرو را شامل می‌شود.
              تفکیک‌ها بر اساس خدمت، لاین و کارمند اولیهٔ ثبت‌شده هنگام رزرو
              هستند؛ جابه‌جایی بعدی کارمند، این انتساب را تغییر نمی‌دهد.
              بازپرداخت جزئی به ترتیب اقلام اولیهٔ فاکتور از مبلغ هر قلم کسر
              می‌شود.
            </p>
          </details>
          <Panel title="روند دریافت و بازپرداخت">
            <CashChart daily={report.data.daily} />
          </Panel>
        </>
      )}
      <RevenueBreakdown query={query} revision={revision} />
      <Documents query={query} refresh={refresh} revision={revision} />
    </>
  );
}

function CashChart({ daily }: { daily: Daily[] }) {
  const maximum = daily.reduce(
    (max, d) =>
      [BigInt(d.received), BigInt(d.refunded), max].reduce((a, b) =>
        a > b ? a : b,
      ),
    BigInt(0),
  );
  return (
    <>
      <p className="finance-legend">
        <span>● دریافت</span>
        <span>● بازپرداخت</span>
      </p>
      {maximum === BigInt(0) ? (
        <Empty>در این بازه گردش مالی قطعی ثبت نشده است.</Empty>
      ) : (
        <div
          className="finance-chart-scroll"
          role="region"
          aria-label="نمودار روزانه؛ جدول ارقام در پایین"
          tabIndex={0}
        >
          <div
            className="finance-chart"
            style={{ minWidth: Math.max(240, daily.length * 22) }}
            aria-hidden="true"
          >
            {daily.map((d) => (
              <div
                className="finance-chart-day"
                key={d.day}
                title={`${dateLabel(d.day, "UTC")} — دریافت ${rials(d.received)}، بازپرداخت ${rials(d.refunded)}`}
              >
                <div className="finance-bars">
                  <i
                    style={{ height: `${chartPercent(d.received, maximum)}%` }}
                  />
                  <i
                    style={{ height: `${chartPercent(d.refunded, maximum)}%` }}
                  />
                </div>
                <span>
                  {new Intl.DateTimeFormat("fa-IR", {
                    month: "numeric",
                    day: "numeric",
                    timeZone: "UTC",
                  }).format(new Date(`${d.day}T12:00:00Z`))}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      <details className="finance-definition">
        <summary>جدول ارقام روزانه</summary>
        <div
          className="finance-table-wrap"
          tabIndex={0}
          role="region"
          aria-label="ارقام روزانه"
        >
          <table className="finance-table">
            <caption className="sr-only">گردش مالی روزانه به ریال</caption>
            <thead>
              <tr>
                <th>روز</th>
                <th>دریافت</th>
                <th>بازپرداخت</th>
                <th>خالص</th>
              </tr>
            </thead>
            <tbody>
              {daily.map((d) => (
                <tr key={d.day}>
                  <th scope="row">{dateLabel(d.day, "UTC")}</th>
                  <td>{rials(d.received)}</td>
                  <td>{rials(d.refunded)}</td>
                  <td>{rials(d.net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

function RevenueBreakdown({
  query,
  revision,
}: {
  query: string;
  revision: number;
}) {
  const [dimension, setDimension] = useState("line");
  return (
    <Panel title="تفکیک دریافتی خدمات">
      <Select
        label="تفکیک بر اساس"
        value={dimension}
        onChange={(e) => setDimension(e.target.value)}
      >
        <option value="line">لاین</option>
        <option value="employee">کارمند اولیهٔ رزرو</option>
        <option value="service">خدمت</option>
      </Select>
      <BreakdownRows
        key={dimension}
        query={`${query}&dimension=${dimension}`}
        revision={revision}
      />
    </Panel>
  );
}
function BreakdownRows({
  query,
  revision,
}: {
  query: string;
  revision: number;
}) {
  const [offset, setOffset] = useState(0);
  const data = useResource<Page<Breakdown>>(
    `/finance/breakdown?${query}&limit=24&offset=${offset}`,
    0,
    api,
    revision,
  );
  return (
    <>
      <ResourceState resource={data} />
      {data.data && !data.error && (
        <>
          {!data.data.items.length ? (
            <Empty />
          ) : (
            <div
              className="finance-table-wrap"
              tabIndex={0}
              role="region"
              aria-label="تفکیک درآمد"
            >
              <table className="finance-table">
                <thead>
                  <tr>
                    <th>عنوان</th>
                    <th>دریافت</th>
                    <th>بازپرداخت</th>
                    <th>خالص</th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.items.map((r) => (
                    <tr key={r.id}>
                      <th scope="row">{r.name}</th>
                      <td>{rials(r.received)}</td>
                      <td>{rials(r.refunded)}</td>
                      <td>{rials(r.net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager
            offset={offset}
            hasMore={data.data.has_more}
            change={setOffset}
          />
        </>
      )}
    </>
  );
}

function Documents({
  query,
  refresh,
  revision,
}: {
  query: string;
  refresh: () => void;
  revision: number;
}) {
  const [kind, setKind] = useState("payments");
  return (
    <Panel title="اسناد و گردش‌های مالی">
      <Select
        label="نوع سند"
        value={kind}
        onChange={(e) => setKind(e.target.value)}
      >
        <option value="payments">دریافت‌های قطعی</option>
        <option value="refunds">درخواست‌های بازپرداخت</option>
        <option value="invoices">فاکتورها</option>
      </Select>
      <p className="muted">
        {kind === "refunds"
          ? "بازهٔ این فهرست بر اساس زمان درخواست است؛ فقط بازپرداخت موفق در جمع گزارش اثر دارد."
          : kind === "invoices"
            ? "بازه بر اساس زمان صدور است. فاکتور مستقل از بازپرداخت، با مبلغ اولیه نگهداری می‌شود."
            : "بازه بر اساس زمان تأیید دریافت است. ماندهٔ قابل بازپرداخت، درخواست‌های باز و بازپرداخت‌های موفق را کسر می‌کند."}
      </p>
      <DocumentRows
        key={kind}
        kind={kind}
        query={query}
        refresh={refresh}
        revision={revision}
      />
    </Panel>
  );
}
function DocumentRows({
  kind,
  query,
  refresh,
  revision,
}: {
  kind: string;
  query: string;
  refresh: () => void;
  revision: number;
}) {
  const [offset, setOffset] = useState(0);
  const data = useResource<Page<FinancialDocument>>(
    `/finance/documents?${query}&kind=${kind}&limit=24&offset=${offset}`,
    kind === "refunds" ? 10000 : 0,
    api,
    revision,
  );
  return (
    <>
      <ResourceState resource={data} />
      {data.data && !data.error && (
        <>
          {!data.data.items.length && <Empty />}
          <div className="finance-documents">
            {data.data.items.map((row) => (
              <DocumentCard
                key={`${row.id}:${row.status}:${row.refundable}`}
                row={row}
                kind={kind}
                refresh={() => {
                  data.reload();
                  refresh();
                }}
              />
            ))}
          </div>
          <Pager
            offset={offset}
            hasMore={data.data.has_more}
            change={setOffset}
          />
        </>
      )}
    </>
  );
}
function DocumentCard({
  row,
  kind,
  refresh,
}: {
  row: FinancialDocument;
  kind: string;
  refresh: () => void;
}) {
  const { workspace } = useWorkspace();
  const write = useWrite();
  const { state } = useAuth();
  const [invoiceOpen, setInvoiceOpen] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const refundable =
    row.refundable !== null && BigInt(row.refundable) > BigInt(0);
  return (
    <article className="finance-document">
      <div className="finance-document-heading">
        <strong>{rials(row.amount)}</strong>
        <span>{refundStatuses[row.status] || row.status}</span>
      </div>
      <p className="muted">
        {dateLabel(row.at, workspace.timezone)} ·{" "}
        {new Intl.DateTimeFormat("fa-IR", {
          hour: "2-digit",
          minute: "2-digit",
          timeZone: workspace.timezone,
        }).format(new Date(row.at))}
      </p>
      <p className="finance-document-number">
        <bdi>{row.number || row.id}</bdi>
      </p>
      {kind === "payments" && (
        <p className="muted">
          {row.allocated ? "تخصیص‌یافته به رزرو" : "تخصیص‌نیافته به رزرو"} ·
          قابل بازپرداخت: {rials(row.refundable || "0")}
        </p>
      )}
      {row.reason && <p>{row.reason}</p>}
      {kind === "invoices" && (
        <>
          <button
            className="button secondary"
            aria-expanded={invoiceOpen}
            onClick={() => setInvoiceOpen((o) => !o)}
          >
            {invoiceOpen ? "بستن فاکتور" : "مشاهدهٔ فاکتور"}
          </button>
          {invoiceOpen && <InvoiceDetails id={row.id} />}
        </>
      )}
      {can(workspace, "payment.refund", row.line_id) &&
        kind === "payments" &&
        refundable && (
          <details>
            <summary>درخواست بازپرداخت</summary>
            <ActionForm
              label="ثبت درخواست بازپرداخت"
              disabled={submitted}
              success="درخواست ثبت شد؛ برای تأیید به فهرست بازپرداخت‌ها بروید."
              submit={async (form) => {
                if (state.status !== "authenticated") return;
                const body = {
                  amount: Number(value(form, "amount")),
                  reason: value(form, "reason"),
                };
                const operation = `refund:${row.id}`;
                const key = mutationKey(state.session.user.id, operation, body);
                await write(
                  `/payments/transactions/${row.id}/refunds`,
                  body,
                  "POST",
                  key,
                );
                setSubmitted(true);
                saveStorage(
                  `operation:${state.session.user.id}:${operation}`,
                  "",
                );
                refresh();
              }}
            >
              <Field
                label="مبلغ بازپرداخت (ریال)"
                name="amount"
                type="number"
                min="1"
                max={
                  BigInt(row.refundable!) < BigInt("1000000000000000")
                    ? row.refundable!
                    : "1000000000000000"
                }
                step="1"
                required
              />
              <Field
                label="دلیل بازپرداخت"
                name="reason"
                maxLength={1000}
                required
              />
              <Check
                label="مبلغ و دلیل را بررسی کردم"
                name="confirmed"
                required
              />
            </ActionForm>
          </details>
        )}
      {can(workspace, "payment.refund", row.line_id) &&
        kind === "refunds" &&
        row.status === "REQUESTED" && (
          <div className="work-grid">
            <ActionForm
              label="تأیید و اجرای بازپرداخت"
              success="نتیجهٔ بازپرداخت به‌روزرسانی شد."
              submit={async () => {
                await write(`/payments/refunds/${row.id}/approve`, {});
                refresh();
              }}
            >
              <Check
                label={`بازپرداخت ${rials(row.amount)} را تأیید می‌کنم`}
                name="confirmed"
                required
              />
            </ActionForm>
            <ActionForm
              label="لغو درخواست"
              success="درخواست لغو شد."
              submit={async () => {
                await write(`/payments/refunds/${row.id}/cancel`, {});
                refresh();
              }}
            >
              <Check
                label="درخواست بازپرداخت لغو شود"
                name="confirmed"
                required
              />
            </ActionForm>
          </div>
        )}
    </article>
  );
}
function InvoiceDetails({ id }: { id: string }) {
  const { workspace } = useWorkspace();
  const data = useResource<InvoiceDocument>(`/finance/invoices/${id}`);
  return (
    <div className="finance-invoice">
      <ResourceState resource={data} />
      {data.data && !data.error && (
        <>
          <h3>فاکتور {data.data.is_test ? "آزمایشی" : "خدمات"}</h3>
          <p>
            فروشنده: {data.data.seller} · خریدار: {data.data.buyer}
          </p>
          <p className="muted">
            تاریخ صدور: {dateLabel(data.data.issued_at, workspace.timezone)}
          </p>
          <ul>
            {data.data.items.map((item, i) => (
              <li key={i}>
                <span>{item.description}</span>
                <strong>{rials(item.amount)}</strong>
              </li>
            ))}
          </ul>
          <p>
            جمع فاکتور: <strong>{rials(data.data.amount)}</strong>
          </p>
        </>
      )}
    </div>
  );
}
