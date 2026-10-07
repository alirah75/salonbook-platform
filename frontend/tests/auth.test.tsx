import { render, screen, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { AuthProvider, useAuth } from "@/components/auth-provider";
import { ToastProvider } from "@/components/toast-provider";
import { AuthForm } from "@/components/auth-form";
import userEvent from "@testing-library/user-event";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
const session = {
  user: {
    id: "one",
    tenant_id: "salon",
    phone: "+989123456789",
    phone_verified: false,
    display_name: "کاربر",
    roles: ["customer"],
  },
  csrf_token: "session-csrf",
  expires_at: new Date(Date.now() + 3600000).toISOString(),
};
function State() {
  const { state, logout } = useAuth();
  return (
    <>
      <span data-testid="state">{state.status}</span>
      <button onClick={() => void logout()}>خروج</button>
    </>
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockClear();
});
describe("session state", () => {
  it("hydrates from the HttpOnly cookie session, then clears on logout", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json(session))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetcher);
    render(
      <AuthProvider>
        <State />
      </AuthProvider>,
    );
    expect(screen.getByTestId("state")).toHaveTextContent("loading");
    await waitFor(() =>
      expect(screen.getByTestId("state")).toHaveTextContent("authenticated"),
    );
    await userEvent.click(screen.getByRole("button", { name: "خروج" }));
    await waitFor(() =>
      expect(screen.getByTestId("state")).toHaveTextContent("anonymous"),
    );
    expect(fetcher.mock.calls[1][1].headers.get("X-CSRF-Token")).toBe(
      "session-csrf",
    );
    expect(localStorage.length).toBe(0);
  });
  it("late session loading cannot restore a session after invalidation", async () => {
    let resolve!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((done) => {
            resolve = done;
          }),
      ),
    );
    render(
      <AuthProvider>
        <State />
      </AuthProvider>,
    );
    act(() => window.dispatchEvent(new Event("salonbook:session-expired")));
    await act(async () => resolve(Response.json(session)));
    expect(screen.getByTestId("state")).toHaveTextContent("anonymous");
  });
  it("validates locally, then logs in with phone and password only", async () => {
    const fetcher = vi.fn((path: string) =>
      Promise.resolve(
        path.endsWith("/me")
          ? Response.json(
              { error: { code: "unauthenticated" } },
              { status: 401 },
            )
          : path.endsWith("/csrf")
            ? Response.json({ csrf_token: "preauth" })
            : Response.json(session),
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    render(
      <AuthProvider>
        <ToastProvider>
          <AuthForm mode="login" />
        </ToastProvider>
      </AuthProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "ورود به حساب" }));
    expect(
      await screen.findByText("رمز عبور را وارد کنید."),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("شماره موبایل"), "09123456789");
    await userEvent.type(
      screen.getByLabelText("رمز عبور"),
      "my-long-passphrase",
    );
    await userEvent.click(screen.getByRole("button", { name: "ورود به حساب" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/account"));
    const calls = (
      fetcher.mock.calls as unknown as [string, RequestInit][]
    ).filter(([path]) => path.endsWith("/login"));
    expect(JSON.parse(calls[0][1].body as string)).toEqual({
      phone: "09123456789",
      password: "my-long-passphrase",
    });
    expect(screen.queryByLabelText(/ایمیل/)).not.toBeInTheDocument();
  });
});
