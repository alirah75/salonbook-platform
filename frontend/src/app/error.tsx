"use client";
import { Button } from "@/components/ui";
export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section className="container narrow state-card">
      <h1>این صفحه باز نشد</h1>
      <p role="alert">مشکلی پیش آمد. دوباره تلاش کنید.</p>
      <Button onClick={reset}>تلاش دوباره</Button>
    </section>
  );
}
