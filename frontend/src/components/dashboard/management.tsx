"use client";
import { useState } from "react";
import {
  can,
  permissionNames,
  roleNames,
  type ManagedUser,
  type Role,
} from "@/lib/dashboard";
import type { Page } from "@/lib/booking";
import { useResource, Pager } from "../booking/resource";
import { Field, PasswordField } from "../ui";
import {
  ActionForm,
  Check,
  Empty,
  Panel,
  ResourceState,
  Select,
  numeric,
  useWorkspace,
  useWrite,
  value,
} from "./shared";

export function UsersPanel() {
  const { workspace } = useWorkspace();
  const write = useWrite();
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState("");
  const users = useResource<Page<ManagedUser>>(
    `/users?limit=24&offset=${offset}${kind ? `&kind=${kind}` : ""}`,
  );
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">حساب‌ها و همکاری</span>
        <h1>حساب‌های سالن</h1>
        <p>شماره موبایل، شناسهٔ ورود هر حساب است.</p>
      </div>
      {can(workspace, "users.manage") && (
        <details className="work-panel work-details">
          <summary>ساخت حساب جدید</summary>
          <ActionForm
            label="ساخت حساب"
            reset
            submit={async (d) => {
              await write("/users", {
                display_name: value(d, "name"),
                phone: value(d, "phone"),
                password: String(d.get("password") ?? ""),
                kind: value(d, "kind"),
              });
              users.reload();
            }}
          >
            <Field
              label="نام و نام خانوادگی"
              name="name"
              required
              maxLength={160}
            />
            <Field
              label="شماره موبایل"
              name="phone"
              required
              inputMode="tel"
              dir="ltr"
              maxLength={32}
            />
            <PasswordField
              label="رمز عبور اولیه"
              name="password"
              required
              minLength={15}
              maxLength={128}
              autoComplete="new-password"
              hint="حداقل ۱۵ نویسه؛ رمز را از راه امن به صاحب حساب بدهید."
            />
            <Select label="نوع حساب" name="kind">
              <option value="customer">مشتری</option>
              <option value="employee">کارمند</option>
            </Select>
          </ActionForm>
        </details>
      )}
      <Select
        label="فیلتر حساب‌ها"
        value={kind}
        onChange={(e) => {
          setKind(e.target.value);
          setOffset(0);
        }}
      >
        <option value="">همهٔ حساب‌ها</option>
        <option value="customer">مشتریان</option>
        <option value="employee">کارکنان</option>
        <option value="manager">مدیران</option>
      </Select>
      <ResourceState resource={users} />
      {users.data && !users.error && (
        <Panel title="فهرست حساب‌ها">
          <div className="work-stack">
            {users.data.items.map((u) => (
              <UserCard
                key={`${u.id}:${JSON.stringify(u)}`}
                user={u}
                done={users.reload}
              />
            ))}
          </div>
          {!users.data.items.length && <Empty />}
          <Pager
            offset={offset}
            hasMore={users.data.has_more}
            change={setOffset}
          />
        </Panel>
      )}
    </>
  );
}
function UserCard({ user, done }: { user: ManagedUser; done: () => void }) {
  const { workspace } = useWorkspace();
  const write = useWrite();
  return (
    <article className="work-item">
      <div className="work-row">
        <h3>{user.display_name}</h3>
        <span className="work-badge">
          {user.is_active ? "فعال" : "غیرفعال"}
        </span>
      </div>
      <p dir="ltr" className="work-phone">
        {user.phone ?? "بدون شمارهٔ ورود"}
      </p>
      <p className="muted">
        {user.assignments
          .map(
            (a) =>
              `${roleNames[a.code] ?? a.code}${a.line_id ? ` (${workspace.lines.find((l) => l.id === a.line_id)?.name ?? "لاین"})` : ""}`,
          )
          .join("، ")}
      </p>
      {can(workspace, "users.manage") && (
        <details className="work-details">
          <summary>ویرایش حساب</summary>
          <ActionForm
            submit={async (d) => {
              await write(
                `/users/${user.id}`,
                { display_name: value(d, "name"), is_active: d.has("active") },
                "PATCH",
              );
              done();
            }}
          >
            <Field
              label="نام و نام خانوادگی"
              name="name"
              defaultValue={user.display_name}
              required
              maxLength={160}
            />
            <Check
              label="ورود این حساب فعال است"
              name="active"
              defaultChecked={user.is_active}
            />
            <p className="muted">
              غیرفعال‌سازی، ورودهای فعلی این حساب را پایان می‌دهد.
            </p>
          </ActionForm>
          {can(workspace, "staff.manage") && (
            <ActionForm
              label="ذخیرهٔ مشخصات کارمند"
              submit={async (d) => {
                await write(
                  `/users/${user.id}/employee`,
                  {
                    public_name: value(d, "public_name"),
                    is_active: d.has("employee_active"),
                  },
                  "PUT",
                );
                done();
              }}
            >
              <Field
                label="نام نمایشی کارمند"
                name="public_name"
                defaultValue={user.employee?.public_name ?? user.display_name}
                maxLength={160}
                required
              />
              <Check
                label="پروفایل کارمند فعال است"
                name="employee_active"
                defaultChecked={user.employee?.is_active ?? true}
              />
            </ActionForm>
          )}
        </details>
      )}
      {can(workspace, "roles.manage") && can(workspace, "roles.read") && (
        <details className="work-details">
          <summary>مدیریت دسترسی این حساب</summary>
          <AssignmentForm user={user} done={done} />
        </details>
      )}
    </article>
  );
}
function AssignmentForm({
  user,
  done,
}: {
  user: ManagedUser;
  done: () => void;
}) {
  const { workspace } = useWorkspace();
  const write = useWrite();
  const [offset, setOffset] = useState(0);
  const [scope, setScope] = useState("TENANT");
  const roles = useResource<Role[]>(`/roles?limit=24&offset=${offset}`);
  return (
    <>
      <p className="muted">
        تغییر دسترسی، ورودهای حساب را پایان می‌دهد تا با مجوز تازه وارد شود.
      </p>
      <ul className="work-list">
        {user.assignments.map((a) => (
          <li key={a.id}>
            <ActionForm
              label="برداشتن نقش"
              submit={async () => {
                await write(`/role-assignments/${a.id}`, {}, "DELETE");
                done();
              }}
            >
              <Check
                name="reviewed"
                label={`برداشتن ${roleNames[a.code] ?? a.code}${a.line_id ? ` از ${workspace.lines.find((l) => l.id === a.line_id)?.name ?? "لاین"}` : " در کل سالن"}`}
                required
              />
            </ActionForm>
          </li>
        ))}
      </ul>
      <ResourceState resource={roles} />
      {roles.data && (
        <>
          <ActionForm
            label="افزودن نقش"
            disabled={!roles.data.length}
            submit={async (d) => {
              await write(`/users/${user.id}/roles`, {
                role_id: value(d, "role"),
                scope: value(d, "scope"),
                line_id: value(d, "scope") === "LINE" ? value(d, "line") : null,
              });
              done();
            }}
          >
            <Select label="نقش" name="role" required>
              {roles.data.map((r) => (
                <option value={r.id} key={r.id}>
                  {roleNames[r.code] ?? r.name}
                </option>
              ))}
            </Select>
            <Select
              label="محدودهٔ نقش"
              name="scope"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="TENANT">کل سالن</option>
              <option value="LINE">فقط یک لاین</option>
            </Select>
            {scope === "LINE" && (
              <Select name="line" label="لاین نقش" required>
                <option value="">انتخاب لاین</option>
                {workspace.lines.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </Select>
            )}
            <Check
              label="نقش و محدوده را بررسی کردم"
              name="reviewed"
              required
            />
          </ActionForm>
          <Pager
            offset={offset}
            hasMore={roles.data.length === 24}
            change={setOffset}
          />
        </>
      )}
    </>
  );
}
export function RolesPanel() {
  const { workspace } = useWorkspace();
  const [offset, setOffset] = useState(0);
  const roles = useResource<Role[]>(`/roles?limit=24&offset=${offset}`);
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">هر مسئولیت، دسترسی مشخص</span>
        <h1>نقش‌ها و دسترسی</h1>
        <p>
          نقش را تعریف کنید؛ محدودهٔ سالن یا لاین هنگام واگذاری آن انتخاب
          می‌شود.
        </p>
      </div>
      {can(workspace, "roles.manage") && (
        <details className="work-details work-panel">
          <summary>ساخت نقش اختصاصی</summary>
          <RoleForm done={roles.reload} />
        </details>
      )}
      <ResourceState resource={roles} />
      {roles.data && !roles.error && (
        <Panel title="نقش‌های سالن">
          <div className="work-stack">
            {roles.data.map((r) => (
              <article
                className="work-item"
                key={`${r.id}:${JSON.stringify(r)}`}
              >
                <div className="work-row">
                  <h3>{roleNames[r.code] ?? r.name}</h3>
                  <span className="work-badge">
                    {r.is_system ? "نقش پایه" : "اختصاصی"}
                  </span>
                </div>
                <ul className="permission-tags">
                  {r.permissions.map((p) => (
                    <li key={p}>{permissionNames[p] ?? p}</li>
                  ))}
                </ul>
                {!r.is_system && can(workspace, "roles.manage") && (
                  <details className="work-details">
                    <summary>ویرایش مجوزهای نقش</summary>
                    <RoleForm role={r} done={roles.reload} />
                  </details>
                )}
              </article>
            ))}
          </div>
          <Pager
            offset={offset}
            hasMore={roles.data.length === 24}
            change={setOffset}
          />
        </Panel>
      )}
    </>
  );
}
function RoleForm({ role, done }: { role?: Role; done: () => void }) {
  const { workspace } = useWorkspace();
  const write = useWrite();
  const permissions =
    useResource<{ code: string; description: string }[]>("/permissions");
  return (
    <>
      <ResourceState resource={permissions} />
      {permissions.data && !permissions.error && (
        <ActionForm
          label={role ? "ذخیرهٔ نقش" : "ساخت نقش"}
          submit={async (d) => {
            await write(
              role ? `/roles/${role.id}` : "/roles",
              {
                name: value(d, "name"),
                permissions: d.getAll("permissions").map(String),
                ...(!role ? { code: value(d, "code") } : {}),
              },
              role ? "PUT" : "POST",
            );
            done();
          }}
        >
          <Field
            label="نام نقش"
            name="name"
            required
            defaultValue={role?.name}
            maxLength={120}
          />
          {!role && (
            <Field
              label="کد لاتین نقش"
              name="code"
              required
              pattern="[a-z][a-z0-9_]{1,79}"
              maxLength={80}
              dir="ltr"
            />
          )}
          <div className="permission-options">
            {permissions.data
              .filter((p) => can(workspace, p.code))
              .map((p) => (
                <label className="work-check" key={p.code}>
                  <input
                    type="checkbox"
                    name="permissions"
                    value={p.code}
                    defaultChecked={role?.permissions.includes(p.code)}
                  />
                  {permissionNames[p.code] ?? p.code}
                </label>
              ))}
          </div>
          <p className="muted">
            فقط مجوزهایی که در کل سالن دارید قابل انتخاب‌اند. تغییر نقش، ورود
            کاربران این نقش را پایان می‌دهد.
          </p>
          <Check
            label="مجوزهای انتخاب‌شده را بررسی کردم"
            name="reviewed"
            required
          />
        </ActionForm>
      )}
    </>
  );
}
const policies = [
  ["hold_minutes", "مهلت پرداخت (دقیقه)", 1, 60],
  ["cancel_before_minutes", "مهلت لغو پیش از نوبت (دقیقه)", 0, 525600],
  ["no_show_grace_minutes", "انتظار برای ثبت عدم حضور (دقیقه)", 0, 240],
  ["slot_step_minutes", "فاصلهٔ نمایش وقت‌ها (دقیقه)", 1, 120],
  ["min_notice_minutes", "حداقل فاصله تا رزرو (دقیقه)", 0, 525600],
  ["booking_horizon_days", "بازهٔ رزرو آینده (روز)", 1, 366],
  ["max_services", "حداکثر خدمات هر نوبت", 1, 20],
  ["max_duration_minutes", "حداکثر مدت نوبت (دقیقه)", 1, 1440],
] as const;
export function SettingsPanel() {
  const { workspace, reload } = useWorkspace();
  const write = useWrite();
  const settings = useResource<Record<string, number>>(
    can(workspace, "schedule.manage") ? "/scheduling/settings" : null,
  );
  return (
    <>
      <div className="work-heading">
        <span className="eyebrow">تنظیمات پایه</span>
        <h1>تنظیمات سالن</h1>
      </div>
      <Panel title="نام سالن">
        <ActionForm
          submit={async (d) => {
            await write("/salon", { name: value(d, "name") }, "PATCH");
            reload();
          }}
        >
          <Field
            label="نام سالن"
            name="name"
            defaultValue={workspace.salon_name}
            required
            maxLength={160}
          />
          <p className="muted">
            زمان‌های برنامه بر اساس منطقهٔ زمانی سالن ({workspace.timezone})
            محاسبه می‌شوند.
          </p>
        </ActionForm>
      </Panel>
      {can(workspace, "schedule.manage") && (
        <Panel title="قواعد رزرو">
          <ResourceState resource={settings} />
          {settings.data && !settings.error && (
            <ActionForm
              key={JSON.stringify(settings.data)}
              submit={async (d) => {
                await write(
                  "/scheduling/settings",
                  Object.fromEntries(
                    policies.map(([key]) => [key, numeric(d, key)]),
                  ),
                  "PUT",
                );
                settings.reload();
              }}
            >
              <div className="work-grid">
                {policies.map(([key, label, min, max]) => (
                  <Field
                    key={key}
                    label={label}
                    name={key}
                    type="number"
                    min={min}
                    max={max}
                    step={1}
                    required
                    defaultValue={settings.data![key]}
                  />
                ))}
              </div>
              <Check
                label="قواعد جدید رزرو را بررسی کردم"
                name="reviewed"
                required
              />
            </ActionForm>
          )}
        </Panel>
      )}
    </>
  );
}
