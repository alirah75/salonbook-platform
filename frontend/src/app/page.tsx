import Link from "next/link";
import { ArrowLeft, Sparkles, ShieldCheck, Smartphone } from "lucide-react";
import { EditorialPanel } from "@/components/shell";

export default function WelcomePage() {
  return (
    <div className="container welcome-grid">
      <section className="welcome-copy">
        <div className="welcome-kicker">
          <span /> به فضای شخصی خود خوش آمدید
        </div>
        <h1>
          برای خودت،
          <br />
          <span>وقت بگذار.</span>
        </h1>
        <p className="hero-description">
          میان شلوغی روزها، جایی برای حالِ خوب شما.
          <br />
          خدمت دلخواه، متخصص شما و زمانی که برایتان مناسب است.
        </p>
        <div className="hero-actions">
          <Link className="button" href="/booking">
            رزرو نوبت
            <ArrowLeft size={19} aria-hidden />
          </Link>
          <Link className="text-link" href="/register">
            ساخت حساب جدید
          </Link>
        </div>
        <div className="welcome-features">
          <div>
            <Smartphone size={21} aria-hidden />
            <span>ورود با موبایل</span>
          </div>
          <div>
            <ShieldCheck size={21} aria-hidden />
            <span>حساب شخصی</span>
          </div>
          <div>
            <Sparkles size={21} aria-hidden />
            <span>ساده و در دسترس</span>
          </div>
        </div>
        <div className="welcome-footnote">
          <span className="tiny-flower" aria-hidden>
            ✳
          </span>
          <p>
            مراقبت از خود،
            <br />
            <strong>یک قرار مهم با خودتان است.</strong>
          </p>
        </div>
      </section>
      <EditorialPanel />
    </div>
  );
}
