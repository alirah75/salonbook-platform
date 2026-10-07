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
import { api, ApiError, errorMessage } from "@/lib/api";
import type { AuthState, Session } from "@/lib/auth-types";
import type { LoginValues, RegisterValues } from "@/lib/forms";

type AuthContextValue = {
  state: AuthState;
  refresh: () => Promise<void>;
  login: (values: LoginValues) => Promise<void>;
  register: (values: RegisterValues) => Promise<void>;
  logout: () => Promise<void>;
};
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const generation = useRef(0);
  const mutating = useRef(false);
  const channel = useRef<BroadcastChannel | null>(null);

  const refresh = useCallback(async () => {
    if (mutating.current) return;
    const version = ++generation.current;
    try {
      const session = await api<Session>("/auth/me");
      if (version === generation.current)
        setState({ status: "authenticated", session });
    } catch (error) {
      if (version !== generation.current) return;
      setState(
        error instanceof ApiError && error.status === 401
          ? { status: "anonymous" }
          : { status: "error", message: errorMessage(error) },
      );
    }
  }, []);

  useEffect(() => {
    // Loading an external session changes state only after the request settles.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const invalidate = () => {
      generation.current++;
    };
    const expired = () => {
      generation.current++;
      setState({ status: "anonymous" });
    };
    const focused = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("salonbook:session-expired", expired);
    document.addEventListener("visibilitychange", focused);
    if (typeof BroadcastChannel !== "undefined") {
      channel.current = new BroadcastChannel("salonbook:auth");
      channel.current.onmessage = () => {
        expired();
        void refresh();
      };
    }
    return () => {
      invalidate();
      channel.current?.close();
      window.removeEventListener("salonbook:session-expired", expired);
      document.removeEventListener("visibilitychange", focused);
    };
  }, [refresh]);

  useEffect(() => {
    if (state.status !== "authenticated") return;
    const wait = Math.max(
      0,
      Math.min(2147483647, Date.parse(state.session.expires_at) - Date.now()),
    );
    const timer = setTimeout(() => void refresh(), wait);
    return () => clearTimeout(timer);
  }, [state, refresh]);

  async function login(values: LoginValues) {
    mutating.current = true;
    const version = ++generation.current;
    try {
      const { csrf_token } = await api<{ csrf_token: string }>("/auth/csrf");
      const session = await api<Session>("/auth/login", {
        method: "POST",
        body: values,
        csrf: csrf_token,
      });
      if (version === generation.current)
        setState({ status: "authenticated", session });
      channel.current?.postMessage("changed");
    } finally {
      generation.current++;
      mutating.current = false;
    }
  }
  async function register(values: RegisterValues) {
    const { csrf_token } = await api<{ csrf_token: string }>("/auth/csrf");
    await api("/auth/register", {
      method: "POST",
      body: values,
      csrf: csrf_token,
    });
  }
  async function logout() {
    if (state.status !== "authenticated") return;
    generation.current++;
    mutating.current = true;
    try {
      await api("/auth/logout", {
        method: "POST",
        body: {},
        csrf: state.session.csrf_token,
      });
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) throw error;
    } finally {
      generation.current++;
      mutating.current = false;
    }
    setState({ status: "anonymous" });
    channel.current?.postMessage("changed");
  }
  return (
    <AuthContext.Provider value={{ state, refresh, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("AuthProvider is required");
  return context;
}
