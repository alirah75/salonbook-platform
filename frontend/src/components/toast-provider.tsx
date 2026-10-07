"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, X, CircleAlert } from "lucide-react";

type Toast = { id: number; text: string; kind: "success" | "error" };
const ToastContext = createContext<
  ((text: string, kind?: Toast["kind"]) => void) | null
>(null);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const sequence = useRef(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const notify = useCallback(
    (text: string, kind: Toast["kind"] = "success") => {
      const id = ++sequence.current;
      setItems((old) => [...old.slice(-2), { id, text, kind }]);
      timers.current.push(
        setTimeout(
          () => setItems((old) => old.filter((item) => item.id !== id)),
          6500,
        ),
      );
    },
    [],
  );
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="toast-region" aria-live="polite" aria-atomic="false">
        {items.map((item) => (
          <div className={`toast ${item.kind}`} key={item.id} role="status">
            {item.kind === "success" ? (
              <CheckCircle2 size={20} aria-hidden />
            ) : (
              <CircleAlert size={20} aria-hidden />
            )}
            <span>{item.text}</span>
            <button
              className="icon-button"
              aria-label="بستن پیام"
              onClick={() =>
                setItems((old) => old.filter((toast) => toast.id !== item.id))
              }
            >
              <X size={18} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("ToastProvider is required");
  return context;
}
