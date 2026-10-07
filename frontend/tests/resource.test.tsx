import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useResource } from "@/components/booking/resource";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn(), errorMessage: () => "خطا" }));
it("a late read cannot replace the successful mutation response", async () => {
  let finishOld!: (value: { version: number }) => void;
  let finishFresh!: (value: { version: number }) => void;
  vi.mocked(api)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishOld = resolve;
        }),
    )
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFresh = resolve;
        }),
    );
  const { result } = renderHook(() =>
    useResource<{ version: number }>("/appointments/example"),
  );
  await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
  act(() => result.current.update({ version: 2 }));
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
  await act(async () => finishOld({ version: 1 }));
  expect(result.current.data?.version).toBe(2);
  await act(async () => finishFresh({ version: 3 }));
  expect(result.current.data?.version).toBe(3);
});
