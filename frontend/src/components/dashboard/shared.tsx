"use client";
import {
  createContext,
  useContext,
  useId,
  useRef,
  useState,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";
import { api, errorMessage } from "@/lib/api";
import type { Workspace } from "@/lib/dashboard";
import { useAuth } from "../auth-provider";
import { useToast } from "../toast-provider";
import { Button, Loading } from "../ui";
import { Failure } from "../booking/resource";

export const WorkspaceContext = createContext<{
  workspace: Workspace;
  reload: () => void;
} | null>(null);
export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("Workspace required");
  return value;
}
export function Select({
  label,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select {...props} id={id}>
        {children}
      </select>
    </div>
  );
}
export function Check({
  label,
  name,
  defaultChecked,
  required = false,
}: {
  label: string;
  name: string;
  defaultChecked?: boolean;
  required?: boolean;
}) {
  return (
    <label className="work-check">
      <input
        type="checkbox"
        name={name}
        defaultChecked={defaultChecked}
        required={required}
      />
      {label}
    </label>
  );
}
export const value = (data: FormData, name: string) =>
  String(data.get(name) ?? "").trim();
export const numeric = (data: FormData, name: string) =>
  Number(value(data, name));
export function useWrite() {
  const { state } = useAuth();
  return <T,>(
    path: string,
    body: unknown,
    method = "POST",
    idempotencyKey?: string,
  ) => {
    if (state.status !== "authenticated")
      return Promise.reject(new Error("Sign in required"));
    return api<T>(path, {
      method,
      body,
      csrf: state.session.csrf_token,
      idempotencyKey,
    });
  };
}
export function ActionForm({
  children,
  submit,
  label = "ذخیرهٔ تغییرات",
  success = "تغییرات ذخیره شد.",
  reset = false,
  disabled = false,
}: {
  children: ReactNode;
  submit: (data: FormData) => Promise<unknown>;
  label?: string;
  success?: string;
  reset?: boolean;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const lock = useRef(false);
  const toast = useToast();
  return (
    <form
      className="work-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (lock.current) return;
        const form = event.currentTarget;
        const data = new FormData(form);
        lock.current = true;
        setBusy(true);
        setError(undefined);
        try {
          await submit(data);
          toast(success);
          if (reset) form.reset();
        } catch (error) {
          setError(errorMessage(error));
        } finally {
          lock.current = false;
          setBusy(false);
        }
      }}
    >
      <fieldset disabled={busy || disabled}>
        {children}
        <Failure message={error} />
        <Button type="submit" busy={busy}>
          {label}
        </Button>
      </fieldset>
    </form>
  );
}
export function ResourceState({
  resource,
}: {
  resource: { loading: boolean; error?: string; reload: () => void };
}) {
  return (
    <>
      {resource.loading && <Loading />}
      <Failure message={resource.error} retry={resource.reload} />
    </>
  );
}
export function Empty({
  children = "هنوز موردی ثبت نشده است.",
}: {
  children?: ReactNode;
}) {
  return <div className="work-empty">{children}</div>;
}
export function Panel({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="work-panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}
