export type FieldIssue = { field: string; code: string; message: string };

export class ApiError extends Error {
  constructor(
    public code: string,
    public status = 0,
    public details: FieldIssue[] = [],
    public requestId?: string,
  ) {
    super(code);
    this.name = "ApiError";
  }
}

const messages: Record<string, string> = {
  report_range: "بازه‌ای معتبر، حداکثر ۳۶۶ روز، انتخاب کنید.",
  refund_exceeds_balance:
    "مبلغ از ماندهٔ قابل بازپرداخت بیشتر است. گزارش را به‌روزرسانی کنید.",
  schedule_conflict:
    "این تغییر با نوبت‌های ثبت‌شده تداخل دارد. ابتدا نوبت‌ها را جابه‌جا کنید.",
  schedule_review_required:
    "تعداد نوبت‌های مرتبط زیاد است؛ تغییر برنامه به بررسی مدیر نیاز دارد.",
  past_block: "زمان شروع مرخصی یا مسدودی باید در آینده باشد.",
  too_early:
    "هنوز زمان ثبت این وضعیت نرسیده است. پس از زمان مقرر دوباره بررسی کنید.",
  last_manager: "سالن باید دست‌کم یک مدیر فعال داشته باشد.",
  inactive_user: "برای این کار یک حساب فعال با شماره موبایل لازم است.",
  inactive_parent: "ابتدا لاین، خدمت یا کارمند مرتبط را فعال کنید.",
  record_conflict: "موردی با این مشخصات وجود دارد. اطلاعات را بررسی کنید.",
  ownership_required: "ابتدا مالکیت دامنه و اتصال آن را بررسی و تأیید کنید.",
  slot_unavailable: "این وقت دیگر آزاد نیست. ساعت دیگری انتخاب کنید.",
  active_hold:
    "یک رزرو در انتظار پرداخت دارید. ابتدا آن را در نوبت‌های من بررسی کنید.",
  pending_booking:
    "یک رزرو در انتظار پرداخت دارید. ابتدا نوبت‌های من را بررسی کنید.",
  booking_window: "این روز خارج از بازهٔ رزرو سالن است. روز دیگری انتخاب کنید.",
  stale_appointment:
    "وضعیت نوبت تغییر کرده است. صفحه را تازه کنید و دوباره بررسی کنید.",
  cancellation_cutoff:
    "مهلت لغو یا تغییر زمان این نوبت گذشته است. با سالن تماس بگیرید.",
  invalid_transition:
    "وضعیت فعلی اجازهٔ این کار را نمی‌دهد. اطلاعات را به‌روزرسانی کنید.",
  not_found: "این مورد در دسترس نیست یا به حساب شما تعلق ندارد.",
  live_hold_required:
    "مهلت پرداخت این رزرو تمام شده یا وضعیت آن تغییر کرده است.",
  payment_in_progress:
    "پرداختی در حال بررسی است. نتیجهٔ همان پرداخت را دنبال کنید.",
  payment_unavailable: "پرداخت این سالن فعلاً فعال نیست. با سالن تماس بگیرید.",
  idempotency_conflict:
    "اطلاعات درخواست تغییر کرده است. ابتدا نوبت‌های ثبت‌شده را بررسی کنید.",
  idempotency_expired:
    "این درخواست قدیمی است. پیش از رزرو دوباره، نوبت‌های من را بررسی کنید.",
  mock_already_resolved:
    "نتیجهٔ این پرداخت قبلاً ثبت شده است. نتیجهٔ پرداخت را مشاهده کنید.",
  unauthenticated: "برای ادامه، دوباره وارد حساب خود شوید.",
  invalid_credentials: "شماره موبایل یا رمز عبور درست نیست.",
  login_failed: "شماره موبایل یا رمز عبور درست نیست.",
  forbidden: "به این بخش دسترسی ندارید.",
  csrf_failed: "اعتبار فرم تمام شده است. صفحه را تازه کنید و دوباره تلاش کنید.",
  rate_limited: "تعداد درخواست‌ها زیاد است. کمی بعد دوباره تلاش کنید.",
  validation_error: "اطلاعات فرم را بررسی کنید.",
  unknown_salon: "این سالن در دسترس نیست.",
  network_error: "ارتباط برقرار نشد. اتصال خود را بررسی و دوباره تلاش کنید.",
  request_timeout: "پاسخ سرور طول کشید. کمی بعد دوباره تلاش کنید.",
};

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError))
    return "مشکلی پیش آمد. لطفاً دوباره تلاش کنید.";
  return (
    messages[error.code] ??
    (error.status === 429
      ? messages.rate_limited
      : error.status === 401
        ? messages.invalid_credentials
        : error.status === 503
          ? "سرویس موقتاً در دسترس نیست. کمی بعد دوباره تلاش کنید."
          : "درخواست انجام نشد. لطفاً دوباره تلاش کنید.")
  );
}

type Options = Omit<RequestInit, "body"> & {
  body?: unknown;
  csrf?: string;
  idempotencyKey?: string;
  timeoutMs?: number;
};

export const api = <T>(path: string, options: Options = {}) =>
  requestApi<T>(path, options, false);
export const platformApi = <T>(path: string, options: Options = {}) =>
  requestApi<T>(path, options, true);
async function requestApi<T>(
  path: string,
  options: Options,
  platform: boolean,
): Promise<T> {
  // Relative, same-origin API only: credentials must never follow a caller-controlled URL.
  if (
    !/^\/[a-zA-Z0-9/?=&._:%-]*$/.test(path) ||
    path.startsWith("//") ||
    path.includes("..")
  )
    throw new ApiError("invalid_api_path");
  const { body, csrf, idempotencyKey, timeoutMs = 15000, ...init } = options;
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (body !== undefined) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  const timeout = AbortSignal.timeout(timeoutMs);
  const signal = init.signal
    ? AbortSignal.any([init.signal, timeout])
    : timeout;
  let response: Response;
  try {
    response = await fetch(`${platform ? "/platform" : ""}/api/v1${path}`, {
      ...init,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
    });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new ApiError(timeout.aborted ? "request_timeout" : "network_error");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const value = payload?.error;
    const failure = new ApiError(
      typeof value?.code === "string" ? value.code : "request_failed",
      response.status,
      Array.isArray(value?.details)
        ? value.details.filter(
            (item: FieldIssue) =>
              typeof item?.field === "string" && typeof item?.code === "string",
          )
        : [],
      response.headers.get("X-Request-ID") ?? undefined,
    );
    if (
      response.status === 401 &&
      path !== "/auth/login" &&
      path !== "/auth/me" &&
      typeof window !== "undefined"
    )
      window.dispatchEvent(
        new Event(
          platform ? "salonbook:platform-expired" : "salonbook:session-expired",
        ),
      );
    throw failure;
  }
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("invalid_response", response.status);
  }
}
