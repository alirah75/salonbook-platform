"use client";
import {
  useEffect,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import Link from "next/link";
import { api, errorMessage } from "@/lib/api";
import { loginUrl } from "@/lib/booking";
import { useAuth } from "../auth-provider";
import { Loading, Button } from "../ui";

export function useResource<T>(
  path: string | null,
  poll = 0,
  client = api,
  revisionKey = 0,
) {
  const [state, setState] = useState<{
    path: string;
    data?: T;
    error?: string;
  }>({ path: "" });
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const reload = useCallback(() => {
    generation.current += 1;
    setRevision((value) => value + 1);
  }, []);
  const update = useCallback(
    (data: T) => {
      reload();
      if (path) setState({ path, data });
    },
    [path, reload],
  );
  useEffect(() => {
    if (!path) return;
    const currentGeneration = ++generation.current;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const data = await client<T>(path!, { signal: controller.signal });
        if (
          !controller.signal.aborted &&
          currentGeneration === generation.current
        )
          setState({ path: path!, data });
      } catch (error) {
        if (
          !controller.signal.aborted &&
          currentGeneration === generation.current
        )
          setState((old) => ({
            path: path!,
            data: old.path === path ? old.data : undefined,
            error: errorMessage(error),
          }));
      } finally {
        if (
          poll &&
          !controller.signal.aborted &&
          currentGeneration === generation.current
        )
          timer = setTimeout(read, poll);
      }
    }
    void read();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [path, revision, poll, client, revisionKey]);
  const current: { data?: T; error?: string } =
    state.path === path ? state : {};
  return {
    ...current,
    loading: !!path && !current.data && !current.error,
    reload,
    update,
  };
}
export function Failure({
  message,
  retry,
}: {
  message?: string;
  retry?: () => void;
}) {
  if (!message) return null;
  return (
    <div className="form-error" role="alert">
      {message}
      {retry && (
        <button type="button" className="inline-action" onClick={retry}>
          تلاش دوباره
        </button>
      )}
    </div>
  );
}
export function PrivatePage({
  path,
  children,
}: {
  path: string;
  children: ReactNode;
}) {
  const { state, refresh } = useAuth();
  if (state.status === "loading") return <Loading />;
  if (state.status === "error")
    return <Failure message={state.message} retry={() => void refresh()} />;
  if (state.status !== "authenticated")
    return (
      <section className="state-card">
        <h1>نوبت شما، در حساب شما</h1>
        <p>
          برای ادامه با شماره موبایل وارد شوید. انتخاب‌های رزرو شما نگه داشته
          می‌شود.
        </p>
        <Link className="button" href={loginUrl(path)}>
          ورود و ادامه
        </Link>
      </section>
    );
  return <div key={state.session.user.id}>{children}</div>;
}
export function Pager({
  offset,
  hasMore,
  change,
}: {
  offset: number;
  hasMore: boolean;
  change: (value: number) => void;
}) {
  return (
    <div className="page-actions">
      <Button
        type="button"
        className="secondary"
        disabled={offset === 0}
        onClick={() => change(Math.max(0, offset - 24))}
      >
        قبلی
      </Button>
      <Button
        type="button"
        className="secondary"
        disabled={!hasMore}
        onClick={() => change(offset + 24)}
      >
        بعدی
      </Button>
    </div>
  );
}
