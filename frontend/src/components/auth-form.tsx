"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import {
  loginSchema,
  registerSchema,
  type LoginValues,
  type RegisterValues,
} from "@/lib/forms";
import { ApiError, errorMessage } from "@/lib/api";
import { safeReturn } from "@/lib/booking";
import { useAuth } from "./auth-provider";
import { useToast } from "./toast-provider";
import { Button, Field, PasswordField } from "./ui";

export function AuthForm({
  mode,
  returnTo,
}: {
  mode: "login" | "register";
  returnTo?: string;
}) {
  const destination = safeReturn(returnTo);
  const loginLink =
    destination === "/account"
      ? "/login"
      : `/login?returnTo=${encodeURIComponent(destination)}`;
  const registerLink =
    destination === "/account"
      ? "/register"
      : `/register?returnTo=${encodeURIComponent(destination)}`;
  const signup = mode === "register";
  const auth = useAuth();
  const toast = useToast();
  const router = useRouter();
  const [formError, setFormError] = useState<string>();
  const [registered, setRegistered] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError,
    resetField,
  } = useForm<RegisterValues>({
    resolver: zodResolver(
      signup
        ? registerSchema
        : loginSchema.extend({ display_name: z.string() }),
    ),
    defaultValues: { phone: "", password: "", display_name: "" },
    mode: "onSubmit",
    reValidateMode: "onChange",
  });
  async function submit(values: RegisterValues) {
    setFormError(undefined);
    try {
      if (signup) {
        await auth.register(values);
        resetField("password");
        setRegistered(true);
        toast("درخواست ثبت‌نام دریافت شد.");
      } else {
        const loginValues: LoginValues = {
          phone: values.phone,
          password: values.password,
        };
        await auth.login(loginValues);
        resetField("password");
        toast("خوش آمدید.");
        router.replace(destination);
      }
    } catch (error) {
      const message = errorMessage(error);
      setFormError(message);
      if (error instanceof ApiError) {
        for (const detail of error.details) {
          const field = detail.field.replace(/^body\./, "");
          if (
            field === "phone" ||
            field === "password" ||
            field === "display_name"
          )
            setError(
              field,
              {
                type: "server",
                message:
                  field === "phone"
                    ? "شماره موبایل معتبر وارد کنید."
                    : "مقدار این بخش را بررسی کنید.",
              },
              { shouldFocus: true },
            );
        }
      }
    }
  }
  if (registered)
    return (
      <div className="success-state">
        <span className="success-icon">
          <ShieldCheck size={30} />
        </span>
        <h1>یک قدم تا حساب شما</h1>
        <p>
          درخواست ثبت‌نام دریافت شد. اکنون با شماره موبایل و رمز عبورتان وارد
          شوید.
        </p>
        <Link href={loginLink} className="button">
          ورود به حساب
          <ArrowLeft size={18} />
        </Link>
      </div>
    );
  return (
    <>
      <div className="form-heading">
        <span className="eyebrow">حساب شخصی شما</span>
        <h1>
          {signup ? "به سالن‌بوک خوش آمدید" : "خوش برگشتید"}
          <span className="accent-dot">.</span>
        </h1>
        <p>
          {signup
            ? "با شماره موبایل، حساب خود را بسازید."
            : "برای ورود، شماره موبایل و رمز عبورتان را وارد کنید."}
        </p>
      </div>
      <form
        onSubmit={handleSubmit(submit)}
        noValidate
        aria-label={signup ? "فرم ثبت‌نام" : "فرم ورود"}
      >
        {formError && (
          <div className="form-error" role="alert">
            {formError}
          </div>
        )}
        {signup && (
          <Field
            label="نام و نام خانوادگی"
            autoComplete="name"
            maxLength={160}
            error={errors.display_name?.message}
            {...register("display_name")}
          />
        )}
        <Field
          label="شماره موبایل"
          placeholder="0912 345 6789"
          dir="ltr"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          maxLength={32}
          error={errors.phone?.message}
          {...register("phone")}
        />
        <PasswordField
          label="رمز عبور"
          dir="ltr"
          autoComplete={signup ? "new-password" : "current-password"}
          maxLength={128}
          hint={
            signup
              ? "دست‌کم ۱۵ نویسه؛ می‌توانید از یک عبارت به‌یادماندنی استفاده کنید."
              : undefined
          }
          error={errors.password?.message}
          {...register("password")}
        />
        {!signup && (
          <Link className="forgot-link" href="/forgot-password">
            رمز عبور را فراموش کرده‌ام
          </Link>
        )}
        <Button type="submit" busy={isSubmitting} className="full-width">
          {isSubmitting
            ? "در حال بررسی…"
            : signup
              ? "ساخت حساب"
              : "ورود به حساب"}
          <ArrowLeft size={18} aria-hidden />
        </Button>
      </form>
      <p className="form-switch">
        {signup ? "قبلاً حساب ساخته‌اید؟" : "هنوز حساب ندارید؟"}{" "}
        <Link href={signup ? loginLink : registerLink}>
          {signup ? "وارد شوید" : "ثبت‌نام کنید"}
        </Link>
      </p>
      <div className="privacy-note">
        <ShieldCheck size={17} aria-hidden />
        <span>اطلاعات حساب شما خصوصی می‌ماند.</span>
      </div>
    </>
  );
}
