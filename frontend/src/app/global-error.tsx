"use client";
export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="fa" dir="rtl">
      <body>
        <main>
          <h1>مشکلی در نمایش صفحه پیش آمد</h1>
          <button onClick={reset}>تلاش دوباره</button>
        </main>
      </body>
    </html>
  );
}
