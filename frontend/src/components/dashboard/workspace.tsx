"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { LayoutDashboard, ArrowLeft, ShieldCheck } from "lucide-react";
import { useAuth } from "../auth-provider";
import { Failure, useResource } from "../booking/resource";
import { Loading } from "../ui";
import { dateLabel, loginUrl } from "@/lib/booking";
import { roleNames, visibleSections, type Workspace } from "@/lib/dashboard";
import { WorkspaceContext } from "./shared";

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const { state, refresh } = useAuth();
  const path = usePathname();
  if (state.status === "loading") return <Loading />;
  if (state.status === "error")
    return <Failure message={state.message} retry={() => void refresh()} />;
  if (state.status === "anonymous")
    return (
      <section className="container narrow state-card">
        <LayoutDashboard size={36} />
        <h1>فضای کاری سالن</h1>
        <p>با شماره موبایلِ حساب کاری خود وارد شوید.</p>
        <Link className="button" href={loginUrl(path)}>
          ورود به فضای کاری
        </Link>
      </section>
    );
  return (
    <WorkspaceContent key={state.session.user.id}>{children}</WorkspaceContent>
  );
}
function WorkspaceContent({ children }: { children: ReactNode }) {
  const context = useResource<Workspace>("/dashboard/context", 60000);
  const path = usePathname();
  if (context.loading) return <Loading label="در حال دریافت فضای کاری…" />;
  // Failed permission refresh never leaves privileged controls visible.
  if (context.error || !context.data)
    return (
      <section className="container narrow state-card">
        <h1>فضای کاری در دسترس نیست</h1>
        <Failure message={context.error} retry={context.reload} />
        <Link href="/account" className="text-link">
          بازگشت به حساب
        </Link>
      </section>
    );
  const workspace = context.data;
  const entries = visibleSections(workspace);
  const allowed = entries.some(
    (item) => path === `/dashboard${item.id ? `/${item.id}` : ""}`,
  );
  return (
    <WorkspaceContext value={{ workspace, reload: context.reload }}>
      <div className="container workspace">
        <aside className="workspace-nav">
          <div className="workspace-brand">
            <LayoutDashboard size={22} />
            <strong>فضای کاری</strong>
          </div>
          <p>{workspace.salon_name}</p>
          <nav aria-label="بخش‌های فضای کاری">
            {entries.map((item) => (
              <Link
                key={item.id}
                href={`/dashboard${item.id ? `/${item.id}` : ""}`}
                aria-current={
                  path === `/dashboard${item.id ? `/${item.id}` : ""}`
                    ? "page"
                    : undefined
                }
              >
                {item.label}
                <ArrowLeft size={15} aria-hidden />
              </Link>
            ))}
          </nav>
          <div className="workspace-access">
            <ShieldCheck size={20} />
            <span>
              {workspace.roles
                .filter((r) => r !== "customer")
                .map((r) => roleNames[r] ?? "نقش اختصاصی")
                .join("، ")}
              <small>دسترسی‌ها مطابق حساب شما</small>
            </span>
          </div>
          <Link className="text-link" href="/account">
            حساب شخصی
          </Link>
        </aside>
        <div className="workspace-body">
          <div className="workspace-top">
            <span>{workspace.salon_name}</span>
            <span>{dateLabel(workspace.today, workspace.timezone)}</span>
          </div>
          {allowed ? (
            children
          ) : (
            <section className="state-card">
              <h1>به این بخش دسترسی ندارید</h1>
              <Link className="button" href="/dashboard">
                نمای کلی
              </Link>
            </section>
          )}
        </div>
      </div>
    </WorkspaceContext>
  );
}
export function WorkspaceLink() {
  const { state } = useAuth();
  const context = useResource<Workspace>(
    state.status === "authenticated" &&
      state.session.user.roles.some((r) => r !== "customer")
      ? "/dashboard/context"
      : null,
  );
  return context.data && !context.error && state.status === "authenticated" ? (
    <Link className="button secondary" href="/dashboard">
      فضای کاری سالن
    </Link>
  ) : null;
}
