import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Decision } from "../api/delivery";
import { NotificationsBell } from "../components/NotificationsBell";

const mocks = vi.hoisted(() => ({ projectDecisions: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, projectDecisions: mocks.projectDecisions } };
});

const blocking: Decision = {
  id: "gate:run-1", kind: "gate_pending", tier: "blocking",
  title: "A run is waiting for your decision", summary: "Parked at the delivery gate.",
  requires_admin: false, actions: [],
};
const standing: Decision = {
  id: "delivered-no-mr", kind: "delivered_no_mr", tier: "standing",
  title: "12 delivered items have no merge request", summary: "Delivered locally.",
  requires_admin: false, actions: [],
};

function mount(projectId: string | null) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <NotificationsBell projectId={projectId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mocks.projectDecisions.mockResolvedValue({ decisions: [blocking, standing] });
});

describe("NotificationsBell", () => {
  it("opens and closes without re-rendering itself to death", async () => {
    // The live instance froze its renderer when the bell was clicked (2026-08-23). This mounts the
    // real component and drives the same interaction: an unbounded render loop or a listener that
    // re-fires its own trigger shows up here as a hang or a state thrash, not as a passing test.
    mount("p1");
    const button = await screen.findByRole("button", { name: /Notifications/ });
    fireEvent.click(button);
    expect(await screen.findByRole("dialog", { name: "Notifications" })).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "true");

    // Closing via the same button must not immediately reopen it: the outside-click listener is on
    // `mousedown` and the toggle on `click`, so a single press fires BOTH — the classic
    // popover-that-cannot-close bug.
    fireEvent.mouseDown(button);
    fireEvent.click(button);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Notifications" })).not.toBeInTheDocument(),
    );
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("renders the panel OUTSIDE the bell's subtree — it must escape the blurred header", async () => {
    // The header carries backdrop-filter: blur(12px). An absolutely-positioned panel inside it
    // forced the browser to re-blur a six-times-larger backdrop and stalled the renderer on the
    // live instance (2026-08-23). This asserts the structural fix, not the styling: if the panel
    // ever becomes a descendant of the bell's wrapper again, it is back inside that layer.
    const { container } = mount("p1");
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    const dialog = await screen.findByRole("dialog", { name: "Notifications" });
    expect(container.contains(dialog)).toBe(false);
    expect(document.body.contains(dialog)).toBe(true);
  });

  it("keeps a click INSIDE the panel from closing it (the portal is not inside the wrapper)", async () => {
    mount("p1");
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    const dialog = await screen.findByRole("dialog", { name: "Notifications" });
    fireEvent.mouseDown(dialog);
    expect(screen.getByRole("dialog", { name: "Notifications" })).toBeInTheDocument();
  });

  it("closes on an outside press and on Escape", async () => {
    mount("p1");
    const button = await screen.findByRole("button", { name: /Notifications/ });
    fireEvent.click(button);
    await screen.findByRole("dialog", { name: "Notifications" });
    fireEvent.mouseDown(document.body);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Notifications" })).not.toBeInTheDocument(),
    );

    fireEvent.click(button);
    await screen.findByRole("dialog", { name: "Notifications" });
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Notifications" })).not.toBeInTheDocument(),
    );
  });

  it("counts BLOCKING conditions only, and says so in its accessible name", async () => {
    mount("p1");
    // A bell that counted dismissible advisories would train the operator to ignore the number —
    // the defect the blocking/standing tiers exist to prevent.
    expect(await screen.findByRole("button", { name: "Notifications — 1 waiting on you" }));
  });

  it("is inert outside a project — there is no cross-project decisions endpoint", async () => {
    mount(null);
    const button = screen.getByRole("button", { name: "Notifications" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocks.projectDecisions).not.toHaveBeenCalled();
  });
});
