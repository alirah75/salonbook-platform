import Link from "next/link";
export default function NotFound() {
  return (
    <section className="container narrow state-card">
      <span className="eyebrow">۴۰۴</span>
      <h1>این صفحه پیدا نشد</h1>
      <p>ممکن است نشانی تغییر کرده باشد.</p>
      <Link href="/" className="button">
        بازگشت به صفحهٔ اصلی
      </Link>
    </section>
  );
}
