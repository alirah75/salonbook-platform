import { z } from "zod";

export function normalizePhone(value: string): string {
  return value
    .trim()
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)))
    .replace(/[\s()-]/g, "");
}
const phone = z
  .string()
  .transform(normalizePhone)
  .pipe(
    z
      .string()
      .regex(
        /^(?:09\d{9}|\+989\d{9}|00989\d{9})$/,
        "شماره موبایل معتبر وارد کنید؛ مانند ۰۹۱۲۳۴۵۶۷۸۹.",
      ),
  );
export const loginSchema = z.object({
  phone,
  password: z
    .string()
    .min(1, "رمز عبور را وارد کنید.")
    .max(128, "رمز عبور بیش از حد طولانی است."),
});
export const registerSchema = loginSchema.extend({
  display_name: z
    .string()
    .trim()
    .min(1, "نام خود را وارد کنید.")
    .max(160, "نام باید کمتر از ۱۶۰ نویسه باشد."),
  password: z
    .string()
    .min(15, "رمز عبور باید دست‌کم ۱۵ نویسه باشد.")
    .max(128, "رمز عبور باید حداکثر ۱۲۸ نویسه باشد."),
});
export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
