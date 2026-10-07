"use client";

import Link from "next/link";
import { useState } from "react";
import {
  LogOut,
  UserRound,
  Smartphone,
  ArrowLeft,
  ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { useToast } from "@/components/toast-provider";
import { Button, Loading } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { WorkspaceLink } from "@/components/dashboard/workspace";

export default function AccountPage() {
  const { state, refresh, logout } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function signOut() {
    setBusy(true);
    try {
      await logout();
      toast("از حساب خارج شدید.");
    } catch (error) {
      toast(errorMessage(error), "error");
    } finally {
      setBusy(false);
    }
  }
  if (state.status === "loading")
    return (
      <div className="container narrow">
        <Loading label="در حال بررسی حساب شما…" />
      </div>
    );
  if (state.status === "error")
    return (
      <section className="container narrow state-card">
        <h1>ارتباط برقرار نشد</h1>
        <p role="alert">{state.message}</p>
        <Button onClick={() => void refresh()}>تلاش دوباره</Button>
      </section>
    );
  if (state.status === "anonymous")
    return (
      <section className="container narrow state-card">
        <span className="success-icon">
          <UserRound size={30} />
        </span>
        <h1>این فضا برای شماست</h1>
        <p>برای مشاهدهٔ حساب، با شماره موبایل وارد شوید.</p>
        <Link href="/login" className="button">
          ورود به حساب
          <ArrowLeft size={18} />
        </Link>
      </section>
    );
  const user = state.session.user;
  return (
    <section className="container narrow account">
      <div className="account-heading">
        <span className="avatar" aria-hidden>
          {Array.from(user.display_name)[0]}
        </span>
        <div>
          <span className="eyebrow">حساب شخصی</span>
          <h1>
            {user.display_name}، خوش آمدید<span className="accent-dot">.</span>
          </h1>
        </div>
      </div>
      <div className="account-panel">
        <div className="page-actions">
          <WorkspaceLink />
          <Link className="button" href="/booking">
            رزرو نوبت جدید
          </Link>
          <Link className="button secondary" href="/appointments">
            نوبت‌های من
          </Link>
        </div>
        <div className="panel-heading">
          <UserRound size={20} />
          <h2>اطلاعات حساب</h2>
        </div>
        <dl>
          <div>
            <dt>نام و نام خانوادگی</dt>
            <dd>{user.display_name}</dd>
          </div>
          <div>
            <dt>
              <Smartphone size={16} />
              شماره موبایل
            </dt>
            <dd dir="ltr">{user.phone ?? "ثبت نشده"}</dd>
          </div>
        </dl>
        <p className="account-note">
          <ShieldCheck size={18} aria-hidden />
          ورود شما با شماره موبایل و رمز عبور انجام شده است.
        </p>
      </div>
      <div className="account-actions">
        <Link href="/" className="text-link">
          بازگشت به صفحهٔ اصلی
        </Link>
        <Button
          className="secondary"
          busy={busy}
          onClick={() => void signOut()}
        >
          <LogOut size={18} aria-hidden />
          خروج از حساب
        </Button>
      </div>
    </section>
  );
}
