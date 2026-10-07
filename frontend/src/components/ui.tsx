"use client";

import {
  useId,
  useState,
  type InputHTMLAttributes,
  type ButtonHTMLAttributes,
} from "react";
import { Eye, EyeOff, LoaderCircle } from "lucide-react";

type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
  hint?: string;
  ref?: React.Ref<HTMLInputElement>;
};
export function Field({
  label,
  error,
  hint,
  id: suppliedId,
  className,
  ...props
}: FieldProps) {
  const generatedId = useId();
  const id = suppliedId ?? generatedId;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        {...props}
        id={id}
        className={className}
        aria-invalid={Boolean(error)}
        aria-describedby={
          error ? `${id}-error` : hint ? `${id}-hint` : undefined
        }
      />
      {error ? (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      ) : hint ? (
        <p className="field-hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
export function PasswordField(props: Omit<FieldProps, "type">) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="password-field">
      <Field {...props} type={visible ? "text" : "password"} />
      <button
        type="button"
        className="password-toggle icon-button"
        aria-label={visible ? "پنهان کردن رمز عبور" : "نمایش رمز عبور"}
        aria-pressed={visible}
        onClick={() => setVisible(!visible)}
      >
        {visible ? <EyeOff size={19} /> : <Eye size={19} />}
      </button>
    </div>
  );
}
export function Button({
  busy,
  children,
  className = "",
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) {
  return (
    <button
      {...props}
      disabled={disabled || busy}
      aria-busy={busy}
      className={`button ${className}`}
    >
      {busy && <LoaderCircle className="spinner" size={18} aria-hidden />}
      {children}
    </button>
  );
}
export function Loading({ label = "یک لحظه صبر کنید…" }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spinner" size={25} aria-hidden />
      <span>{label}</span>
      <span className="skeleton" />
      <span className="skeleton short" />
    </div>
  );
}
