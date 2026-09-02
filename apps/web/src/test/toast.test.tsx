import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ToastProvider, useToast } from "../components/ui/toast";

function Trigger() {
  const { toast } = useToast();
  return (
    <button onClick={() => toast({ title: "Couldn't cancel the run", description: "500 boom", variant: "error" })}>
      go
    </button>
  );
}

describe("toast primitive", () => {
  it("shows a toast on demand and dismisses it on click", async () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    expect(screen.queryByText("Couldn't cancel the run")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "go" }));
    expect(await screen.findByText("Couldn't cancel the run")).toBeInTheDocument();
    expect(screen.getByText("500 boom")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Couldn't cancel the run")).not.toBeInTheDocument();
  });

  it("useToast is a safe no-op with no provider (never crashes a component)", () => {
    // The default context value is a no-op, so a component that toasts renders fine unwrapped.
    expect(() => render(<Trigger />)).not.toThrow();
    fireEvent.click(screen.getByRole("button", { name: "go" }));
    expect(screen.queryByText("Couldn't cancel the run")).not.toBeInTheDocument();
  });
});
