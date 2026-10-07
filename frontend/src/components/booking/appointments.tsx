"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { CalendarDays, CheckCircle2 } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import {
  addDays,
  dateLabel,
  money,
  mutationKey,
  number,
  paymentOpen,
  statuses,
  timeLabel,
  type Appointment,
  type Availability,
  type Page,
  type Payment,
  type Settings,
  type Slot,
} from "@/lib/booking";
import { useAuth } from "../auth-provider";
import { Button, Field, Loading } from "../ui";
import { Failure, Pager, PrivatePage, useResource } from "./resource";
import { Dates } from "./wizard";

export function MyAppointments() {
  return (
    <div className="container booking-page">
      <PrivatePage path="/appointments">
        <AppointmentList />
      </PrivatePage>
    </div>
  );
}
function AppointmentList() {
  const [past, setPast] = useState(false);
  const [offset, setOffset] = useState(0);
  const [now] = useState(() => Date.now());
  const settings = useResource<Settings>("/catalog/booking-settings");
  const query = new URLSearchParams({
    mine: "true",
    starts_from: new Date(past ? now - 365 * 86400000 : now).toISOString(),
    starts_until: new Date(past ? now : now + 366 * 86400000).toISOString(),
    limit: "24",
    offset: String(offset),
  });
  const resource = useResource<Page<Appointment>>(`/appointments?${query}`);
  return (
    <>
      <div className="booking-heading">
        <div>
          <span className="eyebrow">قرارهای شخصی شما</span>
          <h1>نوبت‌های من</h1>
        </div>
        <Link href="/booking" className="button">
          رزرو نوبت جدید
        </Link>
      </div>
      <div className="filter-tabs" aria-label="بازهٔ نوبت‌ها">
        {[false, true].map((value) => (
          <button
            key={String(value)}
            aria-pressed={value === past}
            onClick={() => {
              setPast(value);
              setOffset(0);
            }}
          >
            {value ? "یک سال گذشته" : "نوبت‌های پیش رو"}
          </button>
        ))}
      </div>
      <Failure message={settings.error} retry={settings.reload} />
      <Failure message={resource.error} retry={resource.reload} />
      {(resource.loading || settings.loading) && <Loading />}
      {settings.data && (
        <div className="appointment-list">
          {resource.data?.items.map((appointment) => (
            <Link
              href={`/appointments/${appointment.id}`}
              className="appointment-card"
              key={appointment.id}
            >
              <span className="appointment-symbol">
                <CalendarDays size={27} aria-hidden />
              </span>
              <div>
                <span className={`status-pill status-${appointment.status}`}>
                  {statuses[appointment.status] ?? "نیازمند بررسی"}
                </span>
                <h2>
                  {appointment.items
                    .map((item) => item.service_name)
                    .join("، ")}
                </h2>
                <p>
                  {dateLabel(
                    appointment.starts_at,
                    settings.data!.timezone,
                    true,
                  )}
                </p>
                <p>
                  {appointment.employee_name} ·{" "}
                  {appointment.items[0]?.line_name}
                </p>
              </div>
              <div className="appointment-price">
                <strong>{money(appointment.total_amount)}</strong>
                <span className="text-link">مشاهدهٔ نوبت</span>
              </div>
            </Link>
          ))}
        </div>
      )}
      {resource.data?.items.length === 0 && (
        <div className="empty-state">
          <CalendarDays size={34} aria-hidden />
          <h2>هنوز قراری در این بازه ندارید</h2>
          <p>اولین وقت مراقبت از خودتان را انتخاب کنید.</p>
          <Link className="text-link" href="/booking">
            مشاهدهٔ خدمات
          </Link>
        </div>
      )}
      {resource.data && (offset > 0 || resource.data.has_more) && (
        <Pager
          offset={offset}
          hasMore={resource.data.has_more}
          change={setOffset}
        />
      )}
    </>
  );
}
export function AppointmentPage({ id }: { id: string }) {
  return (
    <div className="container narrow">
      <PrivatePage path={`/appointments/${id}`}>
        <Detail id={id} />
      </PrivatePage>
    </div>
  );
}
function Detail({ id }: { id: string }) {
  const resource = useResource<Appointment>(`/appointments/${id}`, 10000);
  const settings = useResource<Settings>("/catalog/booking-settings");
  const [action, setAction] = useState<"cancel" | "reschedule">();
  if (!resource.data || !settings.data)
    return (
      <>
        <Failure message={resource.error} retry={resource.reload} />
        <Failure message={settings.error} retry={settings.reload} />
        {(resource.loading || settings.loading) && <Loading />}
      </>
    );
  const appointment = resource.data;
  const pending = appointment.status === "AWAITING_PAYMENT";
  const confirmed = appointment.status === "CONFIRMED";
  return (
    <>
      <Link className="back-link" href="/appointments">
        بازگشت به نوبت‌های من
      </Link>
      <div className="detail-heading">
        <span className="success-icon">
          {confirmed ? <CheckCircle2 size={31} /> : <CalendarDays size={31} />}
        </span>
        <span className={`status-pill status-${appointment.status}`}>
          {statuses[appointment.status]}
        </span>
        <h1>
          {confirmed
            ? "قرار شما ثبت شده است"
            : pending
              ? "یک قدم تا قطعی شدن نوبت"
              : "جزئیات نوبت شما"}
        </h1>
      </div>
      <Failure message={resource.error} retry={resource.reload} />
      {appointment.is_test && (
        <p className="test-notice">
          محیط آزمایشی · پرداخت واقعی انجام نمی‌شود.
        </p>
      )}
      <div className="review-card">
        <h2>{appointment.items.map((item) => item.service_name).join("، ")}</h2>
        <p>
          {appointment.items[0]?.line_name} · {appointment.employee_name}
        </p>
        <p>{dateLabel(appointment.starts_at, settings.data.timezone, true)}</p>
        <p>{number(appointment.duration_minutes)} دقیقه</p>
        <hr />
        <p>
          مبلغ نهایی <strong>{money(appointment.total_amount)}</strong>
        </p>
        {appointment.cancellation_reason && (
          <p>دلیل لغو: {appointment.cancellation_reason}</p>
        )}
      </div>
      {pending && (
        <div className="notice">
          <strong>این نوبت هنوز قطعی نیست.</strong>
          <p>
            برای نگه داشتن نوبت، پرداخت را تا{" "}
            {appointment.hold_expires_at
              ? timeLabel(appointment.hold_expires_at, settings.data.timezone)
              : "پایان مهلت رزرو"}{" "}
            تکمیل کنید. پایان مهلت و وضعیت نهایی توسط سالن بررسی می‌شود.
          </p>
        </div>
      )}
      <PaymentActions appointment={appointment} refresh={resource.reload} />
      {(pending || confirmed) && !action && (
        <div className="page-actions">
          <Button className="secondary" onClick={() => setAction("cancel")}>
            لغو نوبت
          </Button>
          {confirmed && (
            <Button
              className="secondary"
              onClick={() => setAction("reschedule")}
            >
              تغییر زمان نوبت
            </Button>
          )}
        </div>
      )}
      {action && (pending || confirmed) && (
        <ChangeAppointment
          key={action}
          appointment={appointment}
          settings={settings.data}
          action={action}
          done={(result) => {
            setAction(undefined);
            if (result) resource.update(result);
            else resource.reload();
          }}
        />
      )}
      <History id={id} version={appointment.version} />
    </>
  );
}
function PaymentActions({
  appointment,
  refresh,
}: {
  appointment: Appointment;
  refresh: () => void;
}) {
  const { state } = useAuth();
  const router = useRouter();
  const [offset, setOffset] = useState(0);
  const payments = useResource<Payment[]>(
    `/payments?appointment_id=${appointment.id}&newest_first=true&limit=24&offset=${offset}`,
    10000,
  );
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<string>();
  async function pay() {
    if (
      state.status !== "authenticated" ||
      lock.current ||
      !payments.data ||
      offset !== 0
    )
      return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const latest = payments.data[0];
      if (latest && paymentOpen(latest.status)) {
        router.push(`/payments/${latest.id}`);
        return;
      }
      const body = { appointment_id: appointment.id };
      const result = await api<Payment>("/payments", {
        method: "POST",
        body,
        csrf: state.session.csrf_token,
        idempotencyKey: mutationKey(
          state.session.user.id,
          `pay:${appointment.id}`,
          { ...body, previous: latest?.id ?? null },
        ),
      });
      router.push(`/payments/${result.id}`);
    } catch (failure) {
      setError(errorMessage(failure));
      payments.reload();
      refresh();
    } finally {
      setBusy(false);
      lock.current = false;
    }
  }
  const canPay = appointment.status === "AWAITING_PAYMENT" && offset === 0;
  return (
    <section className="payment-history">
      <Failure message={payments.error} retry={payments.reload} />
      <Failure message={error} />
      {canPay && (
        <Button
          busy={busy}
          disabled={!payments.data || !!payments.error}
          className="full-width"
          onClick={() => void pay()}
        >
          {busy ? "در حال آماده‌سازی…" : "ادامه به پرداخت"}
        </Button>
      )}
      {payments.data?.map((payment) => (
        <Link
          key={payment.id}
          className="payment-row"
          href={`/payments/${payment.id}/result`}
        >
          <span>
            پرداخت {payment.is_test ? "آزمایشی" : ""} ·{" "}
            {statuses[payment.status] ?? "نیازمند بررسی"}
          </span>
          <span className="text-link">نتیجه و رسید</span>
        </Link>
      ))}
      {payments.data && (offset > 0 || payments.data.length === 24) && (
        <Pager
          offset={offset}
          hasMore={payments.data.length === 24}
          change={setOffset}
        />
      )}
    </section>
  );
}
function ChangeAppointment({
  appointment,
  action,
  settings,
  done,
}: {
  appointment: Appointment;
  action: "cancel" | "reschedule";
  settings: Settings;
  done: (result?: Appointment) => void;
}) {
  const { state } = useAuth();
  const [reason, setReason] = useState("");
  const [expectedVersion] = useState(appointment.version);
  const [day, setDay] = useState<string>();
  const [slot, setSlot] = useState<Slot>();
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<string>();
  const query = new URLSearchParams({
    line_id: appointment.line_id,
    employee_id: appointment.employee_id,
    date_from: day ?? settings.today,
    date_until: addDays(day ?? settings.today, 1),
    limit: "24",
    offset: String(offset),
  });
  appointment.items.forEach((item) =>
    query.append("service_ids", item.service_id),
  );
  const slots = useResource<Availability>(
    action === "reschedule" && day ? `/scheduling/availability?${query}` : null,
  );
  async function submit() {
    if (!reason.trim() || state.status !== "authenticated" || lock.current)
      return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    const body = {
      expected_version: expectedVersion,
      reason: reason.trim(),
      ...(action === "reschedule" && slot
        ? { starts_at: slot.starts_at, employee_id: slot.employee_id }
        : {}),
    };
    try {
      const result = await api<Appointment>(
        `/appointments/${appointment.id}/${action}`,
        {
          method: "POST",
          body,
          csrf: state.session.csrf_token,
          idempotencyKey: mutationKey(
            state.session.user.id,
            `${action}:${appointment.id}`,
            body,
          ),
        },
      );
      done(result);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="change-panel">
      <h2>{action === "cancel" ? "لغو این قرار" : "انتخاب زمان جدید"}</h2>
      <p className="small-note">
        {action === "cancel"
          ? "پس از تأیید لغو، وقت آزاد می‌شود. وضعیت بازگشت مبلغ را در نتیجهٔ پرداخت دنبال کنید."
          : "خدمات، متخصص و مبلغ رزرو حفظ می‌شود. امکان جابه‌جایی در زمان ثبت دوباره بررسی خواهد شد."}
      </p>
      {action === "reschedule" && (
        <>
          <Dates
            settings={settings}
            selected={day}
            choose={(value) => {
              setDay(value);
              setSlot(undefined);
              setOffset(0);
            }}
          />
          <Failure message={slots.error} retry={slots.reload} />
          {slots.loading && <Loading />}
          <div className="slot-grid">
            {slots.data?.items.map((candidate) => (
              <button
                className="choice-card slot-choice"
                key={candidate.starts_at}
                aria-pressed={slot?.starts_at === candidate.starts_at}
                onClick={() => setSlot(candidate)}
              >
                {timeLabel(candidate.starts_at, settings.timezone)}
              </button>
            ))}
          </div>
          {slots.data?.items.length === 0 && (
            <p className="empty-state">در این روز وقت آزادی نیست.</p>
          )}
          {slots.data && (offset > 0 || slots.data.has_more) && (
            <Pager
              offset={offset}
              hasMore={slots.data.has_more}
              change={setOffset}
            />
          )}
        </>
      )}
      <Field
        label="دلیل درخواست"
        maxLength={1000}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
      <Failure message={error} />
      <div className="page-actions">
        <Button
          busy={busy}
          disabled={!reason.trim() || (action === "reschedule" && !slot)}
          onClick={() => void submit()}
        >
          {action === "cancel" ? "تأیید لغو نوبت" : "تأیید زمان جدید"}
        </Button>
        <Button className="secondary" disabled={busy} onClick={() => done()}>
          بازگشت
        </Button>
      </div>
    </section>
  );
}
function History({ id, version }: { id: string; version: number }) {
  return <HistoryList key={version} id={id} />;
}
function HistoryList({ id }: { id: string }) {
  const [offset, setOffset] = useState(0);
  const resource = useResource<
    Page<{ id: string; action: string; reason: string | null }>
  >(`/appointments/${id}/history?limit=24&offset=${offset}`);
  const names: Record<string, string> = {
    created: "ثبت رزرو",
    confirmed: "تأیید رزرو",
    cancelled: "لغو رزرو",
    rescheduled: "تغییر زمان",
    expired: "پایان مهلت پرداخت",
    completed: "انجام خدمت",
    no_show: "عدم حضور",
  };
  return (
    <details className="history">
      <summary>تاریخچهٔ نوبت</summary>
      <Failure message={resource.error} retry={resource.reload} />
      <ul>
        {resource.data?.items.map((item) => (
          <li key={item.id}>
            {names[item.action] ?? "به‌روزرسانی نوبت"}
            {item.reason && <span> · {item.reason}</span>}
          </li>
        ))}
      </ul>
      {resource.data && (offset > 0 || resource.data.has_more) && (
        <Pager
          offset={offset}
          hasMore={resource.data.has_more}
          change={setOffset}
        />
      )}
    </details>
  );
}
