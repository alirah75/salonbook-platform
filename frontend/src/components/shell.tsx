"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpLeft, UserRound } from "lucide-react";
import { useAuth } from "./auth-provider";
import { ThemeToggle } from "./theme-toggle";

export function Header() {
  const { state } = useAuth();
  const platform = usePathname().startsWith("/platform");
  return (
    <header className="site-header">
      <div className="container header-inner">
        <Link href="/" className="brand" aria-label="سالن‌بوک، صفحهٔ اصلی">
          <span className="brand-mark" aria-hidden>
            S<span>.</span>
          </span>
          <span>
            سالن‌بوک<small>SALONBOOK</small>
          </span>
        </Link>
        <nav aria-label="ناوبری اصلی">
          {platform ? (
            <>
              <span>مدیریت پلتفرم</span>
              <ThemeToggle />
            </>
          ) : (
            <>
              <Link className="nav-booking" href="/appointments">
                نوبت‌های من
              </Link>
              <ThemeToggle />
              <span className="nav-divider" />
              {state.status === "authenticated" ? (
                <Link className="nav-account" href="/account">
                  <UserRound size={18} aria-hidden />
                  <span>حساب من</span>
                </Link>
              ) : (
                <Link className="nav-account" href="/login">
                  ورود / ثبت‌نام
                  <ArrowUpLeft size={18} aria-hidden />
                </Link>
              )}
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
export function Footer() {
  return (
    <footer className="site-footer container">
      <span>
        سالن‌بوک <span className="footer-dot">·</span> زمانی برای خودت
      </span>
      <span>با حوصله، برای شما.</span>
    </footer>
  );
}
export function EditorialPanel({ compact = false }: { compact?: boolean }) {
  return (
    <aside
      className={`editorial-panel ${compact ? "compact" : ""}`}
      aria-label="زمانی برای خودت"
    >
      <div className="editorial-top">
        <span>SELF-CARE, SIMPLIFIED</span>
        <span className="editorial-number">01 / YOU</span>
      </div>
      <div className="botanical" aria-hidden>
        <span className="petal p1" />
        <span className="petal p2" />
        <span className="petal p3" />
        <span className="petal p4" />
        <span className="petal p5" />
        <span className="petal p6" />
        <span className="flower-core" />
      </div>
      <div className="editorial-caption">
        <span className="eyebrow">یک مکث، فقط برای تو</span>
        <p>
          زیبایی، از حالِ خوب
          <br />
          شروع می‌شود.
        </p>
        <div className="fine-line" />
        <span className="editorial-note">
          زمانی برای مراقبت. فرصتی برای آرامش.
        </span>
      </div>
    </aside>
  );
}
