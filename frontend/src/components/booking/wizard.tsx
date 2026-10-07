"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, Clock3, Scissors, UserRound } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import {
  addDays,
  dateLabel,
  emptyDraft,
  money,
  mutationKey,
  number,
  parseDraft,
  readStorage,
  saveStorage,
  timeLabel,
  type Appointment,
  type Availability,
  type Draft,
  type Employee,
  type Offer,
  type Page,
  type Service,
  type Settings,
} from "@/lib/booking";
import { useAuth } from "../auth-provider";
import { Button, Field, Loading } from "../ui";
import { Failure, Pager, PrivatePage, useResource } from "./resource";

const steps = ["خدمت", "لاین", "متخصص", "روز", "ساعت", "تأیید"];
type Change = (draft: Draft) => void;

export function BookingWizard() {
  const [draft, setDraft] = useState<Draft>();
  const settings = useResource<Settings>("/catalog/booking-settings");
  useEffect(() => {
    void Promise.resolve().then(() =>
      setDraft(parseDraft(readStorage("booking-draft"))),
    );
  }, []);
  function change(value: Draft) {
    setDraft(value);
    saveStorage("booking-draft", JSON.stringify(value));
  }
  if (!draft || settings.loading) return <Loading />;
  if (!settings.data)
    return <Failure message={settings.error} retry={settings.reload} />;
  const config = settings.data;
  return (
    <div className="container booking-page">
      <div className="booking-heading">
        <div>
          <span className="eyebrow">یک قرار برای حالِ خوب</span>
          <h1>
            وقتِ شماست<span className="accent-dot">.</span>
          </h1>
        </div>
        <Link href="/appointments" className="text-link">
          نوبت‌های من
        </Link>
      </div>
      <ol className="booking-steps" aria-label="مراحل رزرو">
        {steps.map((name, index) => (
          <li
            key={name}
            aria-current={draft.step === index + 1 ? "step" : undefined}
            className={draft.step > index + 1 ? "complete" : ""}
          >
            <span>
              {draft.step > index + 1 ? <Check size={15} /> : number(index + 1)}
            </span>
            {name}
          </li>
        ))}
      </ol>
      <div className="booking-grid">
        <section className="booking-content" aria-live="polite">
          {draft.step > 1 && (
            <button
              className="back-link"
              onClick={() => change({ ...draft, step: draft.step - 1 })}
            >
              بازگشت به مرحلهٔ قبل
            </button>
          )}
          {draft.step === 1 && (
            <Services
              onSelect={(service) =>
                change({
                  version: 1,
                  intent: crypto.randomUUID(),
                  step: 2,
                  service,
                })
              }
            />
          )}
          {draft.step === 2 && (
            <Lines
              key={draft.service!.id}
              service={draft.service!}
              onSelect={(offer) =>
                change({
                  version: 1,
                  intent: draft.intent,
                  step: 3,
                  service: draft.service,
                  offer,
                })
              }
            />
          )}
          {draft.step === 3 && <Employees draft={draft} change={change} />}
          {draft.step === 4 && (
            <Dates
              settings={config}
              selected={draft.day}
              choose={(day) =>
                change({ ...draft, day, slot: undefined, step: 5 })
              }
            />
          )}
          {draft.step === 5 && <Times draft={draft} change={change} />}
          {draft.step === 6 && (
            <PrivatePage path="/booking">
              <Confirmation draft={draft} settings={config} change={change} />
            </PrivatePage>
          )}
        </section>
        <aside className="booking-summary">
          <span className="eyebrow">قرار شما تا اینجا</span>
          <h2>{draft.service?.name ?? "زیبایی، با انتخاب شما"}</h2>
          <div className="summary-flower" aria-hidden>
            ✳
          </div>
          <dl>
            <div>
              <dt>لاین</dt>
              <dd>{draft.offer?.line_name ?? "هنوز انتخاب نشده"}</dd>
            </div>
            <div>
              <dt>متخصص</dt>
              <dd>
                {draft.slot?.employee_name ??
                  draft.employee?.public_name ??
                  "هنوز انتخاب نشده"}
              </dd>
            </div>
            <div>
              <dt>روز و ساعت</dt>
              <dd>
                {draft.day
                  ? dateLabel(draft.day, config.timezone)
                  : "هنوز انتخاب نشده"}
                {draft.slot && (
                  <>
                    <br />
                    {timeLabel(draft.slot.starts_at, config.timezone)}
                  </>
                )}
              </dd>
            </div>
            {draft.offer && (
              <>
                <div>
                  <dt>مدت خدمت</dt>
                  <dd>{number(draft.offer.duration_minutes)} دقیقه</dd>
                </div>
                <div>
                  <dt>مبلغ خدمت</dt>
                  <dd>{money(draft.offer.price_amount)}</dd>
                </div>
              </>
            )}
          </dl>
          <p className="small-note">
            وقت انتخابی تا ثبت رزرو نگه داشته نمی‌شود. مبلغ نهایی پیش از پرداخت
            نمایش داده خواهد شد.
          </p>
          <p className="small-note">
            ساعت‌ها به وقت سالن ({config.timezone}) هستند.
          </p>
        </aside>
      </div>
    </div>
  );
}

function Services({ onSelect }: { onSelect: (service: Service) => void }) {
  const [offset, setOffset] = useState(0);
  const resource = useResource<Page<Service>>(
    `/catalog/services?limit=24&offset=${offset}`,
  );
  return (
    <>
      <span className="eyebrow">۰۱ / انتخاب خدمت</span>
      <h2 className="step-title">امروز، چه مراقبتی می‌خواهید؟</h2>
      <p className="step-description">
        خدمت دلخواهتان را انتخاب کنید؛ قیمت و مدت آن در مرحلهٔ بعد مشخص می‌شود.
      </p>
      <Failure message={resource.error} retry={resource.reload} />
      {resource.loading && <Loading />}
      <div className="choice-grid">
        {resource.data?.items.map((service) => (
          <button
            className="choice-card service-choice"
            key={service.id}
            onClick={() => onSelect(service)}
          >
            <Scissors size={25} aria-hidden />
            <strong>{service.name}</strong>
            <span>{service.description || "زمانی برای مراقبت از شما."}</span>
            <span className="choice-action">
              انتخاب خدمت <ArrowLeft size={16} />
            </span>
          </button>
        ))}
      </div>
      {resource.data?.items.length === 0 && (
        <p className="empty-state">هنوز خدمتی برای رزرو فعال نشده است.</p>
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
function Lines({
  service,
  onSelect,
}: {
  service: Service;
  onSelect: (offer: Offer) => void;
}) {
  const [offset, setOffset] = useState(0);
  const resource = useResource<Page<Offer>>(
    `/catalog/services/${service.id}/lines?limit=24&offset=${offset}`,
  );
  return (
    <>
      <span className="eyebrow">۰۲ / انتخاب لاین</span>
      <h2 className="step-title">فضای مناسبِ شما</h2>
      <p className="step-description">لاین‌های ارائه‌دهندهٔ {service.name}</p>
      <Failure message={resource.error} retry={resource.reload} />
      {resource.loading && <Loading />}
      <div className="choice-list">
        {resource.data?.items.map((offer) => (
          <button
            key={offer.line_id}
            className="choice-card line-choice"
            onClick={() => onSelect(offer)}
          >
            <div>
              <strong>{offer.line_name}</strong>
              <span>
                <Clock3 size={15} aria-hidden />
                {number(offer.duration_minutes)} دقیقه
              </span>
            </div>
            <div>
              <strong>{money(offer.price_amount)}</strong>
              <span className="choice-action">
                انتخاب لاین <ArrowLeft size={16} />
              </span>
            </div>
          </button>
        ))}
      </div>
      {resource.data?.items.length === 0 && (
        <p className="empty-state">
          این خدمت فعلاً در لاینی ارائه نمی‌شود. خدمت دیگری انتخاب کنید.
        </p>
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
function Employees({ draft, change }: { draft: Draft; change: Change }) {
  const [offset, setOffset] = useState(0);
  const resource = useResource<Page<Employee>>(
    `/catalog/lines/${draft.offer!.line_id}/services/${draft.service!.id}/employees?limit=24&offset=${offset}`,
  );
  const choose = (employee: Employee) =>
    change({ ...draft, employee, day: undefined, slot: undefined, step: 4 });
  return (
    <>
      <span className="eyebrow">۰۳ / انتخاب متخصص</span>
      <h2 className="step-title">با چه کسی وقت بگذاریم؟</h2>
      <p className="step-description">
        متخصص دلخواهتان را انتخاب کنید یا انتخاب را به سالن بسپارید.
      </p>
      <Failure message={resource.error} retry={resource.reload} />
      {resource.loading && <Loading />}
      {!!resource.data?.items.length && (
        <button
          className="choice-card auto-choice"
          onClick={() =>
            choose({ id: "auto", public_name: "انتخاب خودکار سالن" })
          }
        >
          <span>
            <strong>اولین وقت مناسب</strong>
            <small>انتخاب متخصص توسط سالن، برای هر ساعت آزاد</small>
          </span>
          <ArrowLeft size={20} />
        </button>
      )}
      <div className="choice-grid">
        {resource.data?.items.map((employee) => (
          <button
            className="choice-card employee-choice"
            key={employee.id}
            onClick={() => choose(employee)}
          >
            <span className="employee-avatar">
              <UserRound size={28} />
            </span>
            <strong>{employee.public_name}</strong>
            <span className="choice-action">
              انتخاب متخصص <ArrowLeft size={16} />
            </span>
          </button>
        ))}
      </div>
      {resource.data?.items.length === 0 && (
        <p className="empty-state">متخصص فعالی برای این خدمت وجود ندارد.</p>
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
export function Dates({
  settings,
  choose,
  selected,
}: {
  settings: Settings;
  choose: (day: string) => void;
  selected?: string;
}) {
  const [week, setWeek] = useState(0);
  const maximum = addDays(settings.today, settings.booking_horizon_days - 1);
  return (
    <>
      <span className="eyebrow">۰۴ / انتخاب روز</span>
      <h2 className="step-title">کدام روز برایتان بهتر است؟</h2>
      <p className="step-description">
        روز را انتخاب کنید تا ساعت‌های آزاد همان روز نمایش داده شود.
      </p>
      <div className="date-grid">
        {Array.from({ length: 7 }, (_, i) =>
          addDays(settings.today, week * 7 + i),
        )
          .filter((day) => day <= maximum)
          .map((day) => (
            <button
              className="choice-card date-choice"
              key={day}
              aria-pressed={day === selected}
              onClick={() => choose(day)}
            >
              <span>
                {new Intl.DateTimeFormat("fa-IR", {
                  weekday: "long",
                  timeZone: "UTC",
                }).format(new Date(`${day}T12:00Z`))}
              </span>
              <strong>
                {new Intl.DateTimeFormat("fa-IR", {
                  day: "numeric",
                  timeZone: "UTC",
                }).format(new Date(`${day}T12:00Z`))}
              </strong>
              <span>
                {new Intl.DateTimeFormat("fa-IR", {
                  month: "long",
                  timeZone: "UTC",
                }).format(new Date(`${day}T12:00Z`))}
              </span>
            </button>
          ))}
      </div>
      <div className="page-actions">
        <Button
          className="secondary"
          disabled={week === 0}
          onClick={() => setWeek(week - 1)}
        >
          هفتهٔ قبل
        </Button>
        <Button
          className="secondary"
          disabled={addDays(settings.today, (week + 1) * 7) > maximum}
          onClick={() => setWeek(week + 1)}
        >
          هفتهٔ بعد
        </Button>
      </div>
      <Field
        type="date"
        label="انتخاب تاریخ دلخواه (میلادی)"
        min={settings.today}
        max={maximum}
        value={selected ?? ""}
        onChange={(event) => {
          const day = event.target.value;
          if (
            /^\d{4}-\d{2}-\d{2}$/.test(day) &&
            day >= settings.today &&
            day <= maximum
          )
            choose(day);
        }}
      />
    </>
  );
}
export function availabilityPath(draft: Draft, offset = 0) {
  const query = new URLSearchParams({
    line_id: draft.offer!.line_id,
    service_ids: draft.service!.id,
    date_from: draft.day!,
    date_until: addDays(draft.day!, 1),
    assignment: "auto",
    limit: "24",
    offset: String(offset),
  });
  if (draft.employee!.id !== "auto")
    query.set("employee_id", draft.employee!.id);
  return `/scheduling/availability?${query}`;
}
function Times({ draft, change }: { draft: Draft; change: Change }) {
  const [offset, setOffset] = useState(0);
  const resource = useResource<Availability>(availabilityPath(draft, offset));
  return (
    <>
      <span className="eyebrow">۰۵ / ساعت‌های آزاد</span>
      <h2 className="step-title">یک ساعت، برای خودتان</h2>
      <p className="step-description">
        {resource.data
          ? dateLabel(draft.day!, resource.data.timezone)
          : "در حال دریافت برنامهٔ سالن"}
      </p>
      <Failure message={resource.error} retry={resource.reload} />
      {resource.loading && <Loading />}
      <div className="slot-grid">
        {resource.data?.items.map((slot) => (
          <button
            className="choice-card slot-choice"
            key={`${slot.employee_id}:${slot.starts_at}`}
            onClick={() => change({ ...draft, slot, step: 6 })}
          >
            <strong>
              {timeLabel(slot.starts_at, resource.data!.timezone)}
            </strong>
            <span>{slot.employee_name}</span>
          </button>
        ))}
      </div>
      {resource.data?.items.length === 0 && (
        <div className="empty-state">
          <p>برای این روز وقت آزادی پیدا نشد.</p>
          <button
            className="inline-action"
            onClick={() => change({ ...draft, step: 4, slot: undefined })}
          >
            انتخاب روز دیگر
          </button>
        </div>
      )}
      {resource.data && (offset > 0 || resource.data.has_more) && (
        <Pager
          offset={offset}
          hasMore={resource.data.has_more}
          change={setOffset}
        />
      )}
      <button className="inline-action" onClick={resource.reload}>
        تازه‌سازی وقت‌ها
      </button>
    </>
  );
}
function Confirmation({
  draft,
  settings,
  change,
}: {
  draft: Draft;
  settings: Settings;
  change: Change;
}) {
  const { state } = useAuth();
  const router = useRouter();
  const resource = useResource<Availability>(availabilityPath(draft));
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<string>();
  async function submit() {
    if (state.status !== "authenticated" || lock.current || !resource.data)
      return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    const body = {
      line_id: draft.offer!.line_id,
      service_ids: [draft.service!.id],
      employee_id: draft.slot!.employee_id,
      starts_at: draft.slot!.starts_at,
    };
    try {
      const result = await api<Appointment>("/appointments", {
        method: "POST",
        body,
        csrf: state.session.csrf_token,
        idempotencyKey: mutationKey(
          state.session.user.id,
          `booking:${draft.intent ?? "legacy"}`,
          body,
        ),
      });
      // A replay is a stored snapshot; the destination always fetches current state.
      saveStorage("booking-draft", JSON.stringify(emptyDraft));
      router.replace(`/appointments/${result.id}`);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
      lock.current = false;
    }
  }
  return (
    <>
      <span className="eyebrow">۰۶ / بررسی نهایی</span>
      <h2 className="step-title">همه‌چیز برای قرار شما آماده است؟</h2>
      <p className="step-description">
        انتخاب‌ها را بررسی کنید. برای خدمات غیررایگان، نوبت پس از تأیید پرداخت
        قطعی می‌شود.
      </p>
      <div className="review-card">
        <h3>{draft.service!.name}</h3>
        <p>
          {draft.offer!.line_name} · {draft.slot!.employee_name}
        </p>
        <p>{dateLabel(draft.slot!.starts_at, settings.timezone, true)}</p>
        <hr />
        <p>
          مبلغ فعلی خدمت{" "}
          <strong>
            {resource.data
              ? money(resource.data.total_amount)
              : "در حال دریافت…"}
          </strong>
        </p>
        <p>
          مدت خدمت{" "}
          <strong>
            {number(
              resource.data?.duration_minutes ?? draft.offer!.duration_minutes,
            )}{" "}
            دقیقه
          </strong>
        </p>
      </div>
      <p className="small-note">
        مهلت معمول لغو و جابه‌جایی: {number(settings.cancel_before_minutes)}{" "}
        دقیقه پیش از نوبت. قوانین ثبت‌شده هنگام رزرو ملاک تصمیم نهایی سالن است.
      </p>
      <Failure message={resource.error} retry={resource.reload} />
      <Failure message={error} />
      {error && (
        <p className="small-note">
          اگر پاسخ ثبت رزرو نرسید، با همین دکمه دوباره تلاش کنید یا{" "}
          <Link className="text-link" href="/appointments">
            نوبت‌های من
          </Link>{" "}
          را بررسی کنید.
        </p>
      )}
      <div className="page-actions">
        <Button
          busy={busy}
          disabled={
            !resource.data ||
            !!resource.error ||
            !Number.isSafeInteger(resource.data.total_amount)
          }
          onClick={() => void submit()}
        >
          {busy
            ? "در حال ثبت…"
            : resource.data?.total_amount === 0
              ? "ثبت نوبت رایگان"
              : "ثبت و ادامه به پرداخت"}
          <ArrowLeft size={18} />
        </Button>
        <Button
          className="secondary"
          disabled={busy}
          onClick={() => change({ ...draft, step: 5 })}
        >
          تغییر ساعت
        </Button>
      </div>
    </>
  );
}
