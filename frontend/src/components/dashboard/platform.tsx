"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Building2, LogOut, ShieldCheck } from "lucide-react";
import { ApiError, errorMessage, platformApi } from "@/lib/api";
import { dateLabel, type Page } from "@/lib/booking";
import { Button, Field, Loading, PasswordField } from "../ui";
import { Failure, Pager, useResource } from "../booking/resource";
import {
  ActionForm,
  Check,
  Empty,
  Panel,
  ResourceState,
  Select,
  value,
} from "./shared";

type PlatformSession = {
  user: { id: string; phone: string; display_name: string };
  csrf_token: string;
  expires_at: string;
};
type Salon = {
  id: string;
  name: string;
  status: string;
  timezone: string;
  created_at: string;
  domains: { hostname: string; is_active: boolean; verified: boolean }[];
};
type Audit = {
  id: string;
  actor_id: string | null;
  entity_id: string | null;
  action: string;
  created_at: string;
  reason: string | null;
};
const labels: Record<string, string> = {
  ACTIVE: "فعال",
  SUSPENDED: "تعلیق شده",
  CLOSED: "بسته شده",
};
export function PlatformConsole() {
  const [state, setState] = useState<{
    loading: boolean;
    session?: PlatformSession;
    error?: string;
  }>({ loading: true });
  const generation = useRef(0);
  const mutating = useRef(false);
  const refresh = useCallback(async () => {
    if (mutating.current) return;
    const epoch = ++generation.current;
    try {
      const session = await platformApi<PlatformSession>("/auth/me");
      if (generation.current === epoch) setState({ loading: false, session });
    } catch (error) {
      if (generation.current === epoch)
        setState({
          loading: false,
          error:
            error instanceof ApiError && error.status === 401
              ? undefined
              : errorMessage(error),
        });
    }
  }, []);
  useEffect(() => {
    const reload = () => void refresh();
    const visible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    const timer = setInterval(reload, 60000);
    // State changes only after the external session request settles.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const invalidate = () => {
      generation.current++;
    };
    window.addEventListener("salonbook:platform-expired", reload);
    document.addEventListener("visibilitychange", visible);
    return () => {
      invalidate();
      clearInterval(timer);
      window.removeEventListener("salonbook:platform-expired", reload);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [refresh]);
  if (state.loading) return <Loading label="در حال بررسی ورود مدیر کل…" />;
  if (!state.session)
    return (
      <section className="container narrow platform-login">
        <span className="success-icon">
          <ShieldCheck size={30} />
        </span>
        <span className="eyebrow">مدیریت سالن‌بوک</span>
        <h1>ورود مدیر کل پلتفرم</h1>
        <p>از شماره موبایل حساب مدیر کل استفاده کنید.</p>
        <Failure message={state.error} retry={() => void refresh()} />
        <ActionForm
          label="ورود به مدیریت پلتفرم"
          success="وارد پنل مدیر کل شدید."
          submit={async (d) => {
            generation.current++;
            mutating.current = true;
            try {
              const session = await platformApi<PlatformSession>(
                "/auth/login",
                {
                  method: "POST",
                  body: {
                    phone: value(d, "phone"),
                    password: String(d.get("password") ?? ""),
                  },
                },
              );
              generation.current++;
              setState({ loading: false, session });
            } finally {
              generation.current++;
              mutating.current = false;
            }
          }}
        >
          <Field
            label="شماره موبایل مدیر کل"
            name="phone"
            dir="ltr"
            required
            inputMode="tel"
            autoComplete="username"
            maxLength={32}
          />
          <PasswordField
            label="رمز عبور مدیر کل"
            name="password"
            required
            maxLength={128}
            autoComplete="current-password"
          />
        </ActionForm>
      </section>
    );
  return (
    <PlatformWorkspace
      key={state.session.user.id}
      session={state.session}
      logout={async () => {
        generation.current++;
        mutating.current = true;
        try {
          await platformApi("/auth/logout", {
            method: "POST",
            body: {},
            csrf: state.session!.csrf_token,
          });
          generation.current++;
          setState({ loading: false });
        } finally {
          generation.current++;
          mutating.current = false;
        }
      }}
    />
  );
}
function PlatformWorkspace({
  session,
  logout,
}: {
  session: PlatformSession;
  logout: () => Promise<void>;
}) {
  const [tab, setTab] = useState("salons");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  return (
    <div className="container workspace platform-workspace">
      <aside className="workspace-nav">
        <div className="workspace-brand">
          <ShieldCheck size={23} />
          <strong>مدیریت پلتفرم</strong>
        </div>
        <p>{session.user.display_name}</p>
        <nav aria-label="بخش‌های مدیر کل">
          <button
            aria-current={tab === "salons" ? "page" : undefined}
            onClick={() => setTab("salons")}
          >
            سالن‌ها
          </button>
          <button
            aria-current={tab === "audit" ? "page" : undefined}
            onClick={() => setTab("audit")}
          >
            تاریخچهٔ عملیات
          </button>
        </nav>
        <Button
          busy={busy}
          className="secondary"
          onClick={async () => {
            setBusy(true);
            try {
              await logout();
            } catch (e) {
              setError(errorMessage(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          <LogOut size={17} />
          خروج مدیر کل
        </Button>
        <Failure message={error} />
      </aside>
      <div className="workspace-body">
        <div className="workspace-top">
          <span>پنل مدیر کل</span>
          <span dir="ltr">{session.user.phone}</span>
        </div>
        {tab === "salons" ? (
          <SalonDirectory session={session} />
        ) : (
          <PlatformAudit />
        )}
      </div>
    </div>
  );
}
function SalonDirectory({ session }: { session: PlatformSession }) {
  const [offset, setOffset] = useState(0);
  const directory = useResource<Page<Salon>>(
    `/salons?limit=24&offset=${offset}`,
    0,
    platformApi,
  );
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">فضایی برای رشد سالن‌ها</span>
        <h1>سالن‌های پلتفرم</h1>
        <p>
          سالن جدید ایجاد کنید و وضعیت فعالیت و دامنه‌های آن را مدیریت کنید.
        </p>
      </div>
      <details className="work-details work-panel">
        <summary>ایجاد سالن جدید</summary>
        <ActionForm
          label="ایجاد سالن و حساب مدیر"
          reset
          submit={async (d) => {
            await platformApi("/salons", {
              method: "POST",
              csrf: session.csrf_token,
              body: {
                name: value(d, "name"),
                hostname: value(d, "hostname"),
                manager: {
                  display_name: value(d, "manager"),
                  phone: value(d, "phone"),
                  password: String(d.get("password") ?? ""),
                },
                reason: value(d, "reason"),
              },
            });
            directory.reload();
          }}
        >
          <div className="work-grid">
            <Field label="نام سالن جدید" name="name" required maxLength={160} />
            <Field
              label="دامنهٔ سالن"
              name="hostname"
              required
              maxLength={253}
              dir="ltr"
              placeholder="salon.example.com"
            />
            <Field
              label="نام مدیر سالن"
              name="manager"
              required
              maxLength={160}
            />
            <Field
              label="شماره موبایل مدیر سالن"
              name="phone"
              required
              maxLength={32}
              dir="ltr"
              inputMode="tel"
            />
          </div>
          <PasswordField
            label="رمز اولیهٔ مدیر سالن"
            name="password"
            required
            minLength={15}
            maxLength={128}
            autoComplete="new-password"
          />
          <Field
            label="دلیل ایجاد سالن"
            name="reason"
            required
            maxLength={500}
          />
          <p className="muted">
            دامنه پس از بررسی مالکیت و مسیر اتصال فعال می‌شود. رمز اولیه را از
            راه امن به مدیر سالن بدهید.
          </p>
        </ActionForm>
      </details>
      <ResourceState resource={directory} />
      {directory.data && !directory.error && (
        <>
          <div className="work-stack">
            {directory.data.items.map((s) => (
              <SalonCard
                key={`${s.id}:${JSON.stringify(s)}`}
                salon={s}
                session={session}
                done={directory.reload}
              />
            ))}
          </div>
          {!directory.data.items.length && <Empty />}
          <Pager
            offset={offset}
            hasMore={directory.data.has_more}
            change={setOffset}
          />
        </>
      )}
    </>
  );
}
function SalonCard({
  salon,
  session,
  done,
}: {
  salon: Salon;
  session: PlatformSession;
  done: () => void;
}) {
  const [operation, setOperation] = useState("add");
  return (
    <article className="work-panel">
      <div className="work-row">
        <h2>
          <Building2 size={23} aria-hidden /> {salon.name}
        </h2>
        <span className="work-badge">{labels[salon.status]}</span>
      </div>
      <p className="muted">
        ایجاد شده در {dateLabel(salon.created_at, salon.timezone)}
      </p>
      <ul className="work-list">
        {salon.domains.map((d) => (
          <li className="work-row" key={d.hostname}>
            <strong dir="ltr">{d.hostname}</strong>
            <span>
              {d.is_active
                ? "فعال"
                : d.verified
                  ? "غیرفعال"
                  : "نیازمند بررسی مالکیت"}
            </span>
          </li>
        ))}
      </ul>
      {salon.status !== "CLOSED" && (
        <details className="work-details">
          <summary>تغییر وضعیت فعالیت</summary>
          <ActionForm
            label="ثبت وضعیت سالن"
            submit={async (d) => {
              await platformApi(`/salons/${salon.id}/status`, {
                method: "PATCH",
                csrf: session.csrf_token,
                body: {
                  status: salon.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE",
                  reason: value(d, "reason"),
                },
              });
              done();
            }}
          >
            <p>
              {salon.status === "ACTIVE"
                ? "با تعلیق سالن، ورودهای فعلی کاربران آن پایان می‌یابد و رزرو تازه متوقف می‌شود."
                : "سالن دوباره فعال می‌شود؛ کاربران باید مجدداً وارد شوند."}
            </p>
            <Field
              label="دلیل تغییر وضعیت"
              name="reason"
              required
              maxLength={500}
            />
            <Check
              label={
                salon.status === "ACTIVE"
                  ? `تعلیق ${salon.name} را تأیید می‌کنم`
                  : `فعال‌سازی ${salon.name} را تأیید می‌کنم`
              }
              name="reviewed"
              required
            />
          </ActionForm>
        </details>
      )}
      <details className="work-details">
        <summary>مدیریت دامنه</summary>
        <ActionForm
          label="ثبت تغییر دامنه"
          submit={async (d) => {
            await platformApi(`/salons/${salon.id}/domains`, {
              method: "POST",
              csrf: session.csrf_token,
              body: {
                hostname: value(d, "hostname"),
                operation,
                reason: value(d, "reason"),
                ownership_verified: d.has("ownership"),
              },
            });
            done();
          }}
        >
          <Select
            label="عملیات دامنه"
            value={operation}
            onChange={(e) => setOperation(e.target.value)}
          >
            <option value="add">افزودن دامنه</option>
            <option value="activate">فعال‌سازی دامنهٔ ثبت‌شده</option>
            <option value="disable">غیرفعال‌سازی دامنه</option>
          </Select>
          {operation === "add" ? (
            <Field
              label="نام دامنه"
              name="hostname"
              dir="ltr"
              required
              maxLength={253}
            />
          ) : (
            <Select label="دامنهٔ ثبت‌شده" name="hostname" required>
              {salon.domains.map((d) => (
                <option key={d.hostname} value={d.hostname}>
                  {d.hostname}
                </option>
              ))}
            </Select>
          )}
          <Field
            label="دلیل تغییر دامنه"
            name="reason"
            required
            maxLength={500}
          />
          {operation === "activate" && (
            <Check
              label="مالکیت دامنه و اتصال آن به این سالن را بررسی و تأیید کرده‌ام"
              name="ownership"
              required
            />
          )}
        </ActionForm>
      </details>
    </article>
  );
}
const actions: Record<string, string> = {
  "platform.login": "ورود مدیر کل",
  "platform.logout": "خروج مدیر کل",
  "platform.bootstrapped": "ایجاد حساب مدیر کل",
  "tenant.created": "ایجاد سالن",
  "tenant.suspended": "تعلیق سالن",
  "tenant.active": "فعال‌سازی سالن",
  "tenant.domain_add": "افزودن دامنه",
  "tenant.domain_activate": "فعال‌سازی دامنه",
  "tenant.domain_disable": "غیرفعال‌سازی دامنه",
  "tenant.manager_bootstrapped": "تعیین مدیر سالن",
};
function PlatformAudit() {
  const [offset, setOffset] = useState(0);
  const audit = useResource<Page<Audit>>(
    `/audit?limit=24&offset=${offset}`,
    0,
    platformApi,
  );
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">رد روشن تغییرات</span>
        <h1>تاریخچهٔ عملیات</h1>
        <p>ورودها و تغییرهای مدیریتی همراه با زمان و دلیل ثبت می‌شوند.</p>
      </div>
      <ResourceState resource={audit} />
      {audit.data && !audit.error && (
        <Panel title="رویدادهای اخیر">
          <div className="work-stack">
            {audit.data.items.map((a) => (
              <article className="work-item" key={a.id}>
                <div className="work-row">
                  <h3>{actions[a.action] ?? "عملیات مدیریتی"}</h3>
                  <span>{dateLabel(a.created_at, "Asia/Tehran", true)}</span>
                </div>
                {a.reason && <p>{a.reason}</p>}
                <details>
                  <summary>شناسه‌های پیگیری</summary>
                  <small>
                    عامل: {a.actor_id ?? "اپراتور سیستم"}
                    <br />
                    موضوع: {a.entity_id ?? "—"}
                  </small>
                </details>
              </article>
            ))}
          </div>
          {!audit.data.items.length && <Empty />}
          <Pager
            offset={offset}
            hasMore={audit.data.has_more}
            change={setOffset}
          />
        </Panel>
      )}
    </>
  );
}
