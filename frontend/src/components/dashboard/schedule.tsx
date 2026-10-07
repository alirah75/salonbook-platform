"use client";
import { useState } from "react";
import {
  can,
  has,
  calendarScopes,
  blockStatuses,
  minuteLabel,
  minuteValue,
  zonedInstant,
  type Block,
  type Calendar,
  type Weekly,
} from "@/lib/dashboard";
import { addDays, dateLabel, type Page, type Employee } from "@/lib/booking";
import { useResource, Pager } from "../booking/resource";
import { Button, Field } from "../ui";
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

const weekdays = [
  "دوشنبه",
  "سه‌شنبه",
  "چهارشنبه",
  "پنجشنبه",
  "جمعه",
  "شنبه",
  "یکشنبه",
];
function calendarLabel(c: Calendar) {
  return [calendarScopes[c.scope], c.employee_name, c.line_name]
    .filter(Boolean)
    .join(" · ");
}
export function SchedulePanel() {
  const { workspace } = useWorkspace();
  const [offset, setOffset] = useState(0);
  const [chosen, setChosen] = useState("");
  const calendars = useResource<Page<Calendar>>(
    `/scheduling/calendars?limit=24&offset=${offset}`,
  );
  const current =
    calendars.data?.items.find((c) => c.id === chosen) ??
    calendars.data?.items[0];
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">زمان برای کار، زمان برای استراحت</span>
        <h1>برنامه و مرخصی</h1>
        <p>تمام زمان‌ها به وقت سالن است؛ تاریخ ورودی فرم‌ها میلادی است.</p>
      </div>
      {has(workspace, "schedule.manage") && (
        <details className="work-panel work-details">
          <summary>ایجاد تقویم کاری</summary>
          <CreateCalendar done={calendars.reload} />
        </details>
      )}
      <ResourceState resource={calendars} />
      {calendars.data && !calendars.error && (
        <>
          <Select
            label="تقویم کاری"
            value={current?.id ?? ""}
            onChange={(e) => setChosen(e.target.value)}
          >
            {calendars.data.items.map((c) => (
              <option key={c.id} value={c.id}>
                {calendarLabel(c)}
              </option>
            ))}
          </Select>
          <Pager
            offset={offset}
            hasMore={calendars.data.has_more}
            change={setOffset}
          />
          {current ? (
            <CalendarEditor key={current.id} calendar={current} />
          ) : (
            <Empty>
              تقویمی در محدودهٔ شما ثبت نشده است. برای ساخت آن با مدیر سالن
              هماهنگ کنید.
            </Empty>
          )}
        </>
      )}
    </>
  );
}
function CreateCalendar({ done }: { done: () => void }) {
  const { workspace } = useWorkspace();
  const write = useWrite();
  const global = can(workspace, "schedule.manage");
  const [scope, setScope] = useState(global ? "SALON" : "LINE");
  const [line, setLine] = useState(
    workspace.lines.filter((l) => can(workspace, "schedule.manage", l.id))[0]
      ?.id ?? "",
  );
  const [offset, setOffset] = useState(0);
  const employeeScope = scope.includes("EMPLOYEE");
  const lineScope = scope.includes("LINE");
  const employees = useResource<Page<Employee & { employee_id?: string }>>(
    employeeScope && has(workspace, "staff.assign", "staff.manage")
      ? lineScope
        ? `/lines/${line}/employees?limit=24&offset=${offset}`
        : `/employees?limit=24&offset=${offset}`
      : null,
  );
  return (
    <ActionForm
      label="ایجاد تقویم"
      submit={async (d) => {
        await write("/scheduling/calendars", {
          scope,
          employee_id: employeeScope ? value(d, "employee") : null,
          line_id: lineScope ? line : null,
        });
        done();
      }}
    >
      <Select
        label="نوع تقویم"
        value={scope}
        onChange={(e) => {
          setScope(e.target.value);
          setOffset(0);
        }}
      >
        {global && <option value="SALON">کل سالن</option>}
        <option value="LINE">لاین</option>
        {has(workspace, "staff.assign", "staff.manage") && (
          <>
            {global && <option value="EMPLOYEE">کارمند</option>}
            <option value="EMPLOYEE_LINE">کارمند در لاین</option>
          </>
        )}
      </Select>
      {lineScope && (
        <Select
          label="لاین تقویم"
          value={line}
          onChange={(e) => {
            setLine(e.target.value);
            setOffset(0);
          }}
          required
        >
          {workspace.lines
            .filter((l) => can(workspace, "schedule.manage", l.id))
            .map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
        </Select>
      )}
      {employeeScope && (
        <>
          <ResourceState resource={employees} />
          <Select label="کارمند تقویم" name="employee" required>
            <option value="">انتخاب کارمند</option>
            {employees.data?.items.map((e) => (
              <option key={e.id} value={e.employee_id ?? e.id}>
                {e.public_name}
              </option>
            ))}
          </Select>
          {employees.data && (
            <Pager
              offset={offset}
              hasMore={employees.data.has_more}
              change={setOffset}
            />
          )}
        </>
      )}
      <p className="muted">بعد از ایجاد، ساعات هفتگی تقویم را تنظیم کنید.</p>
    </ActionForm>
  );
}
function CalendarEditor({ calendar }: { calendar: Calendar }) {
  const { workspace } = useWorkspace();
  const manage = can(workspace, "schedule.manage", calendar.line_id);
  const own =
    workspace.employee_id === calendar.employee_id &&
    can(workspace, "leave.request_own", calendar.line_id);
  const weekly = useResource<Weekly[]>(
    `/scheduling/calendars/${calendar.id}/weekly`,
  );
  return (
    <>
      <Panel title={`ساعات هفتگی · ${calendarLabel(calendar)}`}>
        <ResourceState resource={weekly} />
        {weekly.data &&
          !weekly.error &&
          (manage ? (
            <WeeklyEditor
              key={JSON.stringify(weekly.data)}
              calendar={calendar}
              periods={weekly.data}
              done={weekly.reload}
            />
          ) : (
            <div className="work-stack">
              {weekly.data.length ? (
                weekly.data.map((p, i) => (
                  <div className="work-row work-item" key={i}>
                    <span>
                      {weekdays[p.weekday]} ·{" "}
                      {p.kind === "OPEN" ? "ساعت کار" : "استراحت"}
                    </span>
                    <strong dir="ltr">
                      {minuteLabel(p.start_minute)} –{" "}
                      {minuteLabel(p.end_minute)}
                    </strong>
                    <small>
                      از {dateLabel(p.valid_from, workspace.timezone)}
                      {p.valid_until
                        ? ` تا پیش از ${dateLabel(p.valid_until, workspace.timezone)}`
                        : ""}
                    </small>
                  </div>
                ))
              ) : (
                <Empty>ساعت هفتگی ثبت نشده است.</Empty>
              )}
            </div>
          ))}
      </Panel>
      <Overrides calendar={calendar} manage={manage} />
      <Blocks calendar={calendar} manage={manage} own={own} />
    </>
  );
}
function WeeklyEditor({
  calendar,
  periods,
  done,
}: {
  calendar: Calendar;
  periods: Weekly[];
  done: () => void;
}) {
  const { workspace } = useWorkspace();
  const write = useWrite();
  const [rows, setRows] = useState(
    periods.map((p, i) => ({ ...p, key: String(i) })),
  );
  function update(index: number, changes: Partial<Weekly>) {
    setRows((old) =>
      old.map((r, i) => (i === index ? { ...r, ...changes } : r)),
    );
  }
  return (
    <ActionForm
      label="ذخیرهٔ برنامهٔ هفتگی"
      submit={async () => {
        await write(
          `/scheduling/calendars/${calendar.id}/weekly`,
          {
            periods: rows.map((r) => ({
              weekday: r.weekday,
              kind: r.kind,
              start_minute: r.start_minute,
              end_minute: r.end_minute,
              valid_from: r.valid_from,
              valid_until: r.valid_until,
            })),
          },
          "PUT",
        );
        done();
      }}
    >
      <div className="weekly-rows">
        {rows.map((p, i) => (
          <div className="weekly-row" key={p.key}>
            <Select
              label={`روز بازه ${i + 1}`}
              value={p.weekday}
              onChange={(e) => update(i, { weekday: Number(e.target.value) })}
            >
              {weekdays.map((day, index) => (
                <option key={day} value={index}>
                  {day}
                </option>
              ))}
            </Select>
            <Select
              label={`نوع بازه ${i + 1}`}
              value={p.kind}
              onChange={(e) =>
                update(i, { kind: e.target.value as Weekly["kind"] })
              }
            >
              <option value="OPEN">کار</option>
              <option value="BREAK">استراحت</option>
            </Select>
            <Field
              label={`شروع بازه ${i + 1}`}
              type="time"
              required
              value={minuteLabel(p.start_minute)}
              onChange={(e) => {
                if (e.target.value)
                  update(i, { start_minute: minuteValue(e.target.value) });
              }}
            />
            <Field
              label={`پایان بازه ${i + 1}`}
              required
              pattern="([01][0-9]|2[0-3]):[0-5][0-9]|24:00"
              dir="ltr"
              defaultValue={minuteLabel(p.end_minute)}
              onBlur={(e) => {
                if (e.target.validity.valid)
                  update(i, { end_minute: minuteValue(e.target.value) });
              }}
            />
            <Field
              label={`معتبر از بازه ${i + 1}`}
              type="date"
              required
              value={p.valid_from}
              onChange={(e) => update(i, { valid_from: e.target.value })}
            />
            <Field
              label={`تا پیش از بازه ${i + 1}`}
              type="date"
              value={p.valid_until ?? ""}
              onChange={(e) =>
                update(i, { valid_until: e.target.value || null })
              }
            />
            <Button
              type="button"
              className="secondary"
              aria-label={`حذف بازه ${i + 1}`}
              onClick={() =>
                setRows((old) => old.filter((_, index) => index !== i))
              }
            >
              حذف بازه
            </Button>
          </div>
        ))}
      </div>
      <Button
        type="button"
        className="secondary"
        disabled={rows.length >= 112}
        onClick={() =>
          setRows((old) => [
            ...old,
            {
              key: crypto.randomUUID(),
              weekday: 5,
              kind: "OPEN",
              start_minute: 540,
              end_minute: 1020,
              valid_from: workspace.today,
              valid_until: null,
            },
          ])
        }
      >
        افزودن بازه
      </Button>
      <p className="muted">
        تمام بازه‌های نمایش‌داده‌شده ذخیره می‌شوند. بازهٔ شبانه را در نیمه‌شب به
        دو بخش تقسیم کنید.
      </p>
      <Check
        name="reviewed"
        label="برنامهٔ هفتگی و بازه‌های حذف‌شده را بررسی کردم"
        required
      />
    </ActionForm>
  );
}
type Override = {
  id: string;
  local_date: string;
  mode: string;
  reason: string | null;
  periods: { start_minute: number; end_minute: number }[];
};
function Overrides({
  calendar,
  manage,
}: {
  calendar: Calendar;
  manage: boolean;
}) {
  const { workspace } = useWorkspace();
  const write = useWrite();
  const [day, setDay] = useState(workspace.today);
  const [mode, setMode] = useState("CLOSED");
  const resource = useResource<Override[]>(
    `/scheduling/calendars/${calendar.id}/overrides?date_from=${day}&date_until=${addDays(day, 1)}`,
  );
  const current = resource.data?.[0];
  return (
    <Panel title="تعطیلی و ساعت استثنایی">
      <Field
        label="روز استثنا (میلادی)"
        type="date"
        value={day}
        onChange={(e) => {
          if (e.target.value) setDay(e.target.value);
        }}
      />
      <ResourceState resource={resource} />
      {resource.data && !resource.error && (
        <>
          <p>
            {current
              ? `${current.mode === "CLOSED" ? "تعطیل" : `ساعت ویژه: ${current.periods.map((p) => `${minuteLabel(p.start_minute)}–${minuteLabel(p.end_minute)}`).join("، ")}`} · ${current.reason ?? ""}`
              : "برنامهٔ هفتگی برای این روز اعمال می‌شود."}
          </p>
          {manage && (
            <>
              <details className="work-details">
                <summary>ثبت برنامهٔ استثنایی این روز</summary>
                <ActionForm
                  label="ثبت استثنا"
                  submit={async (d) => {
                    await write(
                      `/scheduling/calendars/${calendar.id}/overrides/${day}`,
                      {
                        mode,
                        periods:
                          mode === "CLOSED"
                            ? []
                            : [
                                {
                                  start_minute: minuteValue(value(d, "start")),
                                  end_minute: minuteValue(value(d, "end")),
                                },
                              ],
                        reason: value(d, "reason") || null,
                      },
                      "PUT",
                    );
                    resource.reload();
                  }}
                >
                  <Select
                    label="برنامهٔ این روز"
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="CLOSED">تعطیل</option>
                    <option value="REPLACE">ساعت کاری ویژه</option>
                  </Select>
                  {mode === "REPLACE" && (
                    <div className="work-grid">
                      <Field
                        label="شروع کار"
                        name="start"
                        type="time"
                        required
                      />
                      <Field
                        label="پایان کار"
                        name="end"
                        type="time"
                        required
                      />
                    </div>
                  )}
                  <Field label="دلیل استثنا" name="reason" maxLength={300} />
                  <Check
                    label="جایگزینی برنامهٔ استثنایی این روز را تأیید می‌کنم"
                    name="reviewed"
                    required
                  />
                </ActionForm>
              </details>
              {current && (
                <ActionForm
                  label="بازگشت به برنامهٔ هفتگی"
                  submit={async () => {
                    await write(
                      `/scheduling/calendars/${calendar.id}/overrides/${day}`,
                      {},
                      "DELETE",
                    );
                    resource.reload();
                  }}
                >
                  <Check
                    label="استثنای این روز برداشته شود"
                    name="reviewed"
                    required
                  />
                </ActionForm>
              )}
            </>
          )}
        </>
      )}
    </Panel>
  );
}
function Blocks({
  calendar,
  manage,
  own,
}: {
  calendar: Calendar;
  manage: boolean;
  own: boolean;
}) {
  const { workspace } = useWorkspace();
  const write = useWrite();
  const [offset, setOffset] = useState(0);
  const resource = useResource<Page<Block>>(
    `/scheduling/calendars/${calendar.id}/blocks?limit=24&offset=${offset}`,
  );
  return (
    <Panel title="مرخصی و زمان‌های مسدود">
      <ResourceState resource={resource} />
      {resource.data && !resource.error && (
        <>
          <div className="work-stack">
            {resource.data.items.map((b) => (
              <article className="work-item" key={`${b.id}:${b.status}`}>
                <div className="work-row">
                  <h3>{b.kind === "LEAVE" ? "مرخصی" : "زمان مسدود"}</h3>
                  <span className="work-badge">
                    {blockStatuses[b.status] ?? b.status}
                  </span>
                </div>
                <p>
                  {dateLabel(b.starts_at, workspace.timezone, true)} تا{" "}
                  {dateLabel(b.ends_at, workspace.timezone, true)}
                </p>
                <p>{b.reason}</p>
                {((["REQUESTED", "APPROVED"].includes(b.status) && manage) ||
                  (b.status === "REQUESTED" && own)) && (
                  <ActionForm
                    label="ثبت وضعیت"
                    submit={async (d) => {
                      await write(
                        `/scheduling/blocks/${b.id}`,
                        { status: value(d, "status") },
                        "PATCH",
                      );
                      resource.reload();
                    }}
                  >
                    <Select name="status" label="وضعیت جدید">
                      {b.status === "REQUESTED" && manage && (
                        <>
                          <option value="APPROVED">تأیید</option>
                          <option value="REJECTED">رد درخواست</option>
                        </>
                      )}
                      <option value="CANCELLED">لغو</option>
                    </Select>
                  </ActionForm>
                )}
              </article>
            ))}
          </div>
          {!resource.data.items.length && <Empty />}
          <Pager
            offset={offset}
            hasMore={resource.data.has_more}
            change={setOffset}
          />
        </>
      )}
      {(manage || own) && (
        <details className="work-details">
          <summary>
            {manage ? "ثبت مرخصی یا زمان مسدود" : "درخواست مرخصی جدید"}
          </summary>
          <ActionForm
            label={manage ? "ثبت بازه" : "ارسال درخواست مرخصی"}
            reset
            submit={async (d) => {
              await write(
                `/scheduling/calendars/${calendar.id}/${manage ? "blocks" : "leave-requests"}`,
                {
                  kind: manage ? value(d, "kind") : "LEAVE",
                  starts_at: zonedInstant(
                    value(d, "start"),
                    workspace.timezone,
                  ),
                  ends_at: zonedInstant(value(d, "end"), workspace.timezone),
                  reason: value(d, "reason"),
                },
              );
              resource.reload();
            }}
          >
            {manage && (
              <Select label="نوع بازه" name="kind">
                <option value="LEAVE">مرخصی</option>
                <option value="BLOCKED">زمان مسدود</option>
              </Select>
            )}
            <Field
              label="شروع به وقت سالن (میلادی)"
              name="start"
              type="datetime-local"
              required
            />
            <Field
              label="پایان به وقت سالن (میلادی)"
              name="end"
              type="datetime-local"
              required
            />
            <Field
              label="دلیل مرخصی یا مسدودی"
              name="reason"
              required
              maxLength={1000}
            />
            {!manage && (
              <p className="muted">
                مرخصی پس از تأیید مدیر در برنامه اعمال می‌شود.
              </p>
            )}
          </ActionForm>
        </details>
      )}
    </Panel>
  );
}
