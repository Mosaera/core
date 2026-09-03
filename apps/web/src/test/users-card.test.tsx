import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../api/authContext";
import { UsersCard } from "../components/settings/UsersCard";

const mocks = vi.hoisted(() => ({
  listUsers: vi.fn(),
  deleteUser: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: { ...mod.api, listUsers: mocks.listUsers, deleteUser: mocks.deleteUser },
  };
});

function renderCard() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <UsersCard />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("/api/auth/status")) {
        return new Response(
          JSON.stringify({
            auth_required: true,
            user: { id: 1, username: "admin", is_admin: true },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response("{}", { status: 200 });
    }),
  );
  mocks.listUsers.mockResolvedValue({
    users: [
      { id: 1, username: "admin", is_admin: true },
      { id: 2, username: "teammate", is_admin: false },
    ],
    max: 5,
  });
});

describe("UsersCard", () => {
  it("you cannot delete your own account", async () => {
    // The server only refuses the LAST admin, so with a second admin present this button was a
    // one-click self-lockout and the "(you)" marker beside it was purely cosmetic.
    renderCard();
    expect(await screen.findByRole("button", { name: "Remove admin" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove admin" })).toHaveAttribute(
      "title",
      "You can't remove your own account",
    );
  });

  it("other accounts stay removable", async () => {
    renderCard();
    expect(await screen.findByRole("button", { name: "Remove teammate" })).toBeEnabled();
  });
});
