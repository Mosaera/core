import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DriftRecovery } from "../components/delivery/DriftRecovery";

const mocks = vi.hoisted(() => ({ resetProjectClone: vi.fn() }));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, resetProjectClone: mocks.resetProjectClone } };
});

function renderDrift() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DriftRecovery projectId="p1" detail="base drift: origin/main and the local tip diverge" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.resetProjectClone.mockResolvedValue({ reset: true, detail: "abc123 → def456" });
});

describe("DriftRecovery", () => {
  it("shows the drift explanation and keeps the reset button disarmed until 'reset' is typed", async () => {
    renderDrift();
    expect(screen.getByText(/base drift: origin\/main/)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: "Reset clone to remote" });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Type reset to confirm" }), {
      target: { value: "not it" },
    });
    expect(btn).toBeDisabled();
  });

  it("arms on typing 'reset' and calls the reset endpoint", async () => {
    renderDrift();
    fireEvent.change(screen.getByRole("textbox", { name: "Type reset to confirm" }), {
      target: { value: "reset" },
    });
    const btn = screen.getByRole("button", { name: "Reset clone to remote" });
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    await waitFor(() => expect(mocks.resetProjectClone).toHaveBeenCalledWith("p1"));
    expect(await screen.findByText(/reset: abc123 → def456/)).toBeInTheDocument();
  });

  it("surfaces a 409-while-busy error inline rather than silently dropping it", async () => {
    mocks.resetProjectClone.mockRejectedValue(new Error("a run is active on this project"));
    renderDrift();
    fireEvent.change(screen.getByRole("textbox", { name: "Type reset to confirm" }), {
      target: { value: "reset" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reset clone to remote" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("a run is active on this project");
  });
});
