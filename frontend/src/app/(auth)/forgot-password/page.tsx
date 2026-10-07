import Link from "next/link";
import { KeyRound, ArrowRight } from "lucide-react";
export const metadata = { title: "بازیابی دسترسی" };
export default function RecoveryPage() {
  return (
    <div className="recovery">
      <span className="success-icon">
        <KeyRound size={28} aria-hidden />
      </span>
      <span className="eyebrow">بازیابی دسترسی</span>
      <h1>رمزتان را فراموش کرده‌اید؟</h1>
      <p>
        بازیابی خودکار رمز هنوز فعال نیست. برای راهنمایی، با سالن خود تماس
        بگیرید.
      </p>
      <p className="muted">در این نسخه کد پیامکی ارسال نمی‌شود.</p>
      <Link className="button secondary" href="/login">
        <ArrowRight size={18} aria-hidden />
        بازگشت به ورود
      </Link>
    </div>
  );
}
