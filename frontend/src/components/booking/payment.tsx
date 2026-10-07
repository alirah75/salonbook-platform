"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { CheckCircle2, Clock3, FlaskConical } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import {
  money,
  paymentConfirmed,
  paymentOpen,
  statuses,
  type Payment,
} from "@/lib/booking";
import { useAuth } from "../auth-provider";
import { Button, Loading } from "../ui";
import { Failure, PrivatePage, useResource } from "./resource";

export function PaymentPage({
  id,
  result = false,
}: {
  id: string;
  result?: boolean;
}) {
  return (
    <div className="container narrow">
      <PrivatePage path={`/payments/${id}${result ? "/result" : ""}`}>
        <Checkout id={id} result={result} />
      </PrivatePage>
    </div>
  );
}
function Checkout({ id, result }: { id: string; result: boolean }) {
  const { state } = useAuth();
  const router = useRouter();
  const resource = useResource<Payment>(`/payments/${id}`, 5000);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<string>();
  async function simulate(scenario: string) {
    if (state.status !== "authenticated" || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      await api<Payment>(`/payments/${id}/mock-checkout`, {
        method: "POST",
        csrf: state.session.csrf_token,
        body: { scenario },
      });
      router.replace(`/payments/${id}/result`);
      resource.reload();
    } catch (failure) {
      setError(errorMessage(failure));
      resource.reload();
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  if (!resource.data)
    return (
      <>
        <Failure message={resource.error} retry={resource.reload} />
        {resource.loading && <Loading />}
      </>
    );
  const payment = resource.data;
  const confirmed = paymentConfirmed(payment);
  const canCheckout =
    payment.is_test &&
    payment.appointment_status === "AWAITING_PAYMENT" &&
    ["CREATED", "PENDING"].includes(payment.status) &&
    !!payment.checkout_path;
  const pending = paymentOpen(payment.status);
  const showCheckout = !result && canCheckout;
  return (
    <>
      <Link
        className="back-link"
        href={`/appointments/${payment.appointment_id}`}
      >
        مشاهدهٔ نوبت
      </Link>
      <div className="detail-heading">
        <span className="success-icon">
          {showCheckout ? (
            <FlaskConical size={30} />
          ) : confirmed ? (
            <CheckCircle2 size={30} />
          ) : (
            <Clock3 size={30} />
          )}
        </span>
        <span className="eyebrow">
          {showCheckout ? "۰۷ / پرداخت" : "۰۸ / نتیجهٔ پرداخت"}
        </span>
        <h1>
          {showCheckout
            ? "پرداخت آزمایشی"
            : confirmed
              ? "پرداخت و نوبت تأیید شد"
              : pending
                ? "منتظر نتیجهٔ پرداخت هستیم"
                : "نتیجهٔ پرداخت شما"}
        </h1>
      </div>
      {payment.is_test && (
        <p className="test-notice">
          این پرداخت فقط برای آزمایش است. پولی از حساب شما برداشت نمی‌شود؛
          اطلاعات بانکی وارد نکنید.
        </p>
      )}
      <div className="review-card">
        <p>
          مبلغ <strong>{money(payment.amount)}</strong>
        </p>
        <p>
          وضعیت پرداخت{" "}
          <strong>{statuses[payment.status] ?? "نیازمند بررسی"}</strong>
        </p>
        <p>
          وضعیت نوبت{" "}
          <strong>
            {statuses[payment.appointment_status] ?? "نیازمند بررسی"}
          </strong>
        </p>
      </div>
      <Failure message={resource.error} retry={resource.reload} />
      <Failure message={error} />
      {showCheckout ? (
        <>
          <Button
            className="full-width"
            busy={busy}
            disabled={!!resource.error}
            onClick={() => void simulate("success")}
          >
            پرداخت موفق آزمایشی
          </Button>
          <details className="history">
            <summary>حالت‌های دیگر آزمایش</summary>
            <div className="page-actions">
              <Button
                className="secondary"
                busy={busy}
                onClick={() => void simulate("failure")}
              >
                پرداخت ناموفق
              </Button>
              <Button
                className="secondary"
                busy={busy}
                onClick={() => void simulate("cancel")}
              >
                انصراف از پرداخت
              </Button>
              <Button
                className="secondary"
                busy={busy}
                onClick={() => void simulate("timeout")}
              >
                پاسخ با تأخیر
              </Button>
              <Button
                className="secondary"
                busy={busy}
                onClick={() => void simulate("amount_mismatch")}
              >
                مغایرت مبلغ
              </Button>
            </div>
          </details>
        </>
      ) : (
        <>
          <p className="notice">
            {confirmed
              ? "رسید پرداخت ثبت شده و نوبت شما قطعی است."
              : pending
                ? "نتیجه به‌صورت خودکار بررسی می‌شود. تا مشخص شدن آن دوباره پرداخت نکنید؛ می‌توانید بعداً از نوبت‌های من وضعیت را ببینید."
                : payment.transactions.length > 0
                  ? "دریافت وجه به‌تنهایی به معنی تأیید نوبت نیست. وضعیت نوبت و بازگشت وجه را در همین صفحه دنبال کنید."
                  : "این پرداخت نوبت را قطعی نکرده است. برای بررسی مهلت رزرو و تلاش دوباره، به جزئیات نوبت برگردید."}
          </p>
          {canCheckout && (
            <Link className="button" href={`/payments/${id}`}>
              ادامهٔ همین پرداخت
            </Link>
          )}
        </>
      )}
      {payment.transactions.map((transaction) => (
        <section className="receipt-card" key={transaction.id}>
          <h2>رسید پرداخت {payment.is_test && "آزمایشی"}</h2>
          <p className="receipt-number" dir="ltr">
            {transaction.receipt_number}
          </p>
          <p>
            {money(transaction.amount)} ·{" "}
            {transaction.allocated
              ? "اختصاص‌یافته به نوبت"
              : "به نوبت اختصاص نیافته"}
          </p>
          {transaction.refunds.map((refund) => (
            <p key={refund.id}>
              بازگشت مبلغ: {money(refund.amount)} ·{" "}
              <strong>{statuses[refund.status] ?? "در حال بررسی"}</strong>
            </p>
          ))}
        </section>
      ))}
      {!showCheckout && (
        <div className="page-actions">
          <Link
            className="button"
            href={`/appointments/${payment.appointment_id}`}
          >
            جزئیات نوبت
          </Link>
          <Link className="button secondary" href="/appointments">
            نوبت‌های من
          </Link>
          <button className="inline-action" onClick={resource.reload}>
            بررسی دوبارهٔ وضعیت
          </button>
        </div>
      )}
    </>
  );
}
