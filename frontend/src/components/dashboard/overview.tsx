"use client";
import { useState } from "react";
import Link from "next/link";
import { CalendarDays, CheckCircle2, Clock3, UsersRound } from "lucide-react";
import { useResource, Pager } from "../booking/resource";
import { Field } from "../ui";
import {
  addDays,
  dateLabel,
  money,
  mutationKey,
  number,
  statuses,
  timeLabel,
} from "@/lib/booking";
import {
  can,
  has,
  visibleSections,
  zonedInstant,
  type Overview,
  type WorkAppointment,
} from "@/lib/dashboard";
import { useAuth } from "../auth-provider";
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

export function WorkOverview() {
  const { workspace } = useWorkspace();
  const [day, setDay] = useState(workspace.today);
  const [line, setLine] = useState("");
  const [offset, setOffset] = useState(0);
  const readable = has(
    workspace,
    "appointment.read",
    "appointment.read_assigned",
  );
  const data = useResource<Overview>(
    readable
      ? `/dashboard/overview?day=${day}&limit=24&offset=${offset}${line ? `&line_id=${line}` : ""}`
      : null,
    30000,
  );
  const count = data.data?.counts;
  const metrics = [
    [
      "نوبت‌های روز",
      count && Object.values(count).reduce((a, b) => a + b, 0),
      CalendarDays,
    ],
    ["تأیید شده", count?.CONFIRMED ?? 0, UsersRound],
    ["انجام شده", count?.COMPLETED ?? 0, CheckCircle2],
    ["در انتظار پرداخت", count?.AWAITING_PAYMENT ?? 0, Clock3],
  ] as const;
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">ریتم روز کاری شما</span>
        <h1>
          امروز، با برنامه<span className="accent-dot">.</span>
        </h1>
        <p>نوبت‌ها و کارهای مرتبط با مسئولیت شما، در یک نگاه.</p>
      </div>
      {!readable ? (
        <Panel title="بخش‌های در دسترس">
          <div className="work-shortcuts">
            {visibleSections(workspace)
              .filter((s) => s.id)
              .map((s) => (
                <Link
                  className="button secondary"
                  key={s.id}
                  href={`/dashboard/${s.id}`}
                >
                  {s.label}
                </Link>
              ))}
          </div>
        </Panel>
      ) : (
        <>
          <div className="work-filters">
            <Field
              label="روز کاری (میلادی)"
              type="date"
              value={day}
              required
              onChange={(e) => {
                if (e.target.value) {
                  setDay(e.target.value);
                  setOffset(0);
                }
              }}
            />
            <Select
              label="لاین"
              value={line}
              onChange={(e) => {
                setLine(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">همهٔ لاین‌های مجاز</option>
              {workspace.lines.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </Select>
            <div className="page-actions">
              <button
                className="button secondary"
                onClick={() => {
                  setDay(addDays(day, -1));
                  setOffset(0);
                }}
              >
                روز قبل
              </button>
              <button
                className="button secondary"
                onClick={() => {
                  setDay(workspace.today);
                  setOffset(0);
                }}
              >
                امروز
              </button>
              <button
                className="button secondary"
                onClick={() => {
                  setDay(addDays(day, 1));
                  setOffset(0);
                }}
              >
                روز بعد
              </button>
            </div>
          </div>
          <ResourceState resource={data} />
          {data.data && !data.error && (
            <>
              <div className="work-metrics">
                {metrics.map(([label, total, Icon]) => (
                  <section key={label}>
                    <Icon size={21} aria-hidden />
                    <span>{label}</span>
                    <strong>{number(total ?? 0)}</strong>
                  </section>
                ))}
              </div>
              <Panel title={`نوبت‌های ${dateLabel(day, workspace.timezone)}`}>
                <p className="muted">
                  آخرین دریافت:{" "}
                  {timeLabel(data.data.generated_at, workspace.timezone)} ·
                  زمان‌ها به وقت سالن
                </p>
                {!data.data.appointments.items.length && (
                  <Empty>برای این روز و محدوده، نوبتی ثبت نشده است.</Empty>
                )}
                <div className="work-stack">
                  {data.data.appointments.items.map((row) => (
                    <AppointmentCard
                      key={`${row.id}:${row.version}`}
                      row={row}
                      reload={data.reload}
                    />
                  ))}
                </div>
                <Pager
                  offset={offset}
                  hasMore={data.data.appointments.has_more}
                  change={setOffset}
                />
              </Panel>
            </>
          )}
        </>
      )}
    </>
  );
}
function AppointmentCard({
  row,
  reload,
}: {
  row: WorkAppointment;
  reload: () => void;
}) {
  const { workspace } = useWorkspace();
  const write = useWrite();
  const { state } = useAuth();
  const [action, setAction] = useState("complete");
  const manage = can(workspace, "appointment.manage", row.line_id);
  const finish =
    manage ||
    (workspace.employee_id === row.employee_id &&
      can(workspace, "appointment.finish_assigned"));
  const mutable =
    (row.status === "CONFIRMED" && (finish || manage)) ||
    (row.status === "AWAITING_PAYMENT" && manage);
  return (
    <article className="work-appointment">
      <div className="work-appointment-time">
        <strong>{timeLabel(row.starts_at, workspace.timezone)}</strong>
        <span>{timeLabel(row.ends_at, workspace.timezone)}</span>
      </div>
      <div className="work-appointment-content">
        <div className="work-row">
          <h3>{row.customer_name}</h3>
          <span className="work-badge">
            {statuses[row.status] ?? row.status}
          </span>
        </div>
        <p>{row.items.map((i) => i.service_name).join("، ")}</p>
        <small>
          {row.employee_name} ·{" "}
          {row.items[0]?.line_name ??
            workspace.lines.find((l) => l.id === row.line_id)?.name}
        </small>
        {row.total_amount !== null && (
          <p className="muted">{money(row.total_amount)}</p>
        )}
        {mutable && (
          <details className="work-details">
            <summary>مدیریت این نوبت</summary>
            <ActionForm
              label="ثبت تغییر نوبت"
              submit={async (data) => {
                const operation = value(data, "action");
                const body = {
                  expected_version: row.version,
                  reason: value(data, "reason"),
                  ...(["cancel", "reschedule"].includes(operation)
                    ? { override_policy: data.has("override") }
                    : {}),
                  ...(operation === "reschedule"
                    ? {
                        starts_at: zonedInstant(
                          value(data, "starts_at"),
                          workspace.timezone,
                        ),
                        employee_id: row.employee_id,
                      }
                    : {}),
                };
                const key = mutationKey(
                  state.status === "authenticated" ? state.session.user.id : "",
                  `work-${row.id}-${operation}`,
                  body,
                );
                await write(
                  `/appointments/${row.id}/${operation}`,
                  body,
                  "POST",
                  key,
                );
                reload();
              }}
            >
              <Select
                label="عملیات نوبت"
                name="action"
                value={
                  action === "complete" &&
                  (!finish || row.status !== "CONFIRMED")
                    ? "cancel"
                    : action
                }
                onChange={(e) => setAction(e.target.value)}
              >
                {finish && row.status === "CONFIRMED" && (
                  <>
                    <option value="complete">ثبت انجام خدمت</option>
                    <option value="no-show">ثبت عدم حضور</option>
                  </>
                )}
                {manage && (
                  <>
                    <option value="cancel">لغو نوبت</option>
                    <option value="reschedule">
                      تغییر زمان، با همین کارمند
                    </option>
                  </>
                )}
              </Select>
              {action === "reschedule" && (
                <Field
                  label="زمان جدید به وقت سالن (میلادی)"
                  type="datetime-local"
                  name="starts_at"
                  required
                />
              )}
              <Field
                label="دلیل یا توضیح"
                name="reason"
                maxLength={1000}
                required
              />
              {manage &&
                can(workspace, "appointment.override", row.line_id) &&
                ["cancel", "reschedule"].includes(action) && (
                  <Check
                    label="اعمال استثنا برای مهلت لغو یا جابه‌جایی"
                    name="override"
                  />
                )}
              <p className="muted">
                آزاد بودن زمان و وضعیت نوبت هنگام ثبت دوباره بررسی می‌شود.
              </p>
              <Check
                label="اطلاعات و عملیات انتخاب‌شده را بررسی کردم"
                name="reviewed"
                required
              />
            </ActionForm>
          </details>
        )}
      </div>
    </article>
  );
}
