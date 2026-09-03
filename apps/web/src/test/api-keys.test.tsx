import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiKeyRow } from "../api/keys";
import { ApiKeysCard } from "../components/settings/ApiKeysCard";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  revoke: vi.fn(),
}));

vi.mock("../api/keys", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/keys")>();
  return { ...mod, keysApi: { ...mod.keysApi, ...mocks } };
});

function row(over: Partial<ApiKeyRow> = {}): ApiKeyRow {
  return {
    id: 1,
    name: "ci",
    created_at: "2026-08-31T10:00:00Z",
    last_used_at: null,
    revoked: false,
    ...over,
  };
}

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ApiKeysCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue({ keys: [] });
});

describe("API keys", () => {
  it("tells the operator a key is NOT an admin credential", async () => {
    // The copy is the control here. Without it a user reasonably assumes their own key inherits
    // their privileges — and for an admin that assumption is exactly backwards.
    renderCard();
    await waitFor(() => expect(mocks.list).toHaveBeenCalled());
    expect(screen.getByText(/never an admin credential/i)).toBeTruthy();
    expect(screen.getByText(/cannot change configuration/i)).toBeTruthy();
  });

  it("shows the plaintext once, and says so unmissably", async () => {
    mocks.create.mockResolvedValue({ ...row(), key: "sk-the-only-time-you-see-this" });
    renderCard();
    await waitFor(() => expect(mocks.list).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Key name"), { target: { value: "ci" } });
    fireEvent.click(screen.getByRole("button", { name: /create key/i }));

    await waitFor(() => expect(screen.getByText("sk-the-only-time-you-see-this")).toBeTruthy());
    expect(screen.getByText(/only time you will see this key/i)).toBeTruthy();
    // A dismissed-too-early key is unrecoverable, so the remedy must be stated, not implied.
    expect(screen.getByText(/cannot show it again/i)).toBeTruthy();
  });

  it("never renders a secret for an EXISTING key — the list has no way back to one", async () => {
    mocks.list.mockResolvedValue({ keys: [row({ name: "laptop" })] });
    const { container } = renderCard();
    await waitFor(() => expect(screen.getByText("laptop")).toBeTruthy());
    expect(container.textContent).not.toMatch(/sk-/);
    expect(container.textContent).not.toMatch(/token_hash/);
  });

  it("says 'never' for an unused key rather than leaving it blank", async () => {
    // Blank reads as missing data; "never" is the answer an operator needs before revoking.
    mocks.list.mockResolvedValue({ keys: [row({ last_used_at: null })] });
    renderCard();
    await waitFor(() => expect(screen.getByText("never")).toBeTruthy());
  });

  it("confirms before revoking, and does not revoke on the first click", async () => {
    mocks.list.mockResolvedValue({ keys: [row()] });
    mocks.revoke.mockResolvedValue({ revoked: true });
    renderCard();
    await waitFor(() => expect(screen.getByText("ci")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /^revoke$/i }));
    expect(mocks.revoke).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /^revoke$/i }));
    await waitFor(() => expect(mocks.revoke).toHaveBeenCalledWith(1));
  });

  it("a revoked key stays visible rather than vanishing", async () => {
    // Revocation is a soft delete server-side because the row is the audit record; the UI must
    // not imply the credential never existed.
    mocks.list.mockResolvedValue({ keys: [row({ revoked: true })] });
    renderCard();
    await waitFor(() => expect(screen.getByText("ci")).toBeTruthy());
    expect(screen.getByText("revoked")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^revoke$/i })).toBeNull();
  });

  it("refuses to submit an empty or whitespace name", async () => {
    renderCard();
    await waitFor(() => expect(mocks.list).toHaveBeenCalled());
    const button = screen.getByRole("button", { name: /create key/i });
    expect(button.hasAttribute("disabled")).toBe(true);

    fireEvent.change(screen.getByLabelText("Key name"), { target: { value: "   " } });
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("surfaces a server refusal instead of failing silently", async () => {
    mocks.create.mockRejectedValue(new Error("at most 20 live keys — revoke one first"));
    renderCard();
    await waitFor(() => expect(mocks.list).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Key name"), { target: { value: "one-too-many" } });
    fireEvent.click(screen.getByRole("button", { name: /create key/i }));
    await waitFor(() => expect(screen.getByText(/at most 20 live keys/i)).toBeTruthy());
  });
});

describe("API keys — red team round 3 (the browser is where the plaintext lives)", () => {
  it("never writes the key to localStorage or sessionStorage", async () => {
    // The plaintext exists in this component and nowhere else it should. Persisting it would
    // outlive the tab, survive a logout, and be readable by anything sharing the origin.
    mocks.create.mockResolvedValue({ ...row(), key: "sk-must-not-persist" });
    renderCard();
    await waitFor(() => expect(mocks.list).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Key name"), { target: { value: "ci" } });
    fireEvent.click(screen.getByRole("button", { name: /create key/i }));
    await waitFor(() => expect(screen.getByText("sk-must-not-persist")).toBeTruthy());

    expect(JSON.stringify(localStorage)).not.toMatch(/sk-must-not-persist/);
    expect(JSON.stringify(sessionStorage)).not.toMatch(/sk-must-not-persist/);
  });

  it("clears the key from the DOM once dismissed", async () => {
    // "Done" must actually drop it, not merely hide it behind a style — a hidden node is still
    // in the DOM for any extension or screenshot tool that walks it.
    mocks.create.mockResolvedValue({ ...row(), key: "sk-dismiss-me" });
    const { container } = renderCard();
    await waitFor(() => expect(mocks.list).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Key name"), { target: { value: "ci" } });
    fireEvent.click(screen.getByRole("button", { name: /create key/i }));
    await waitFor(() => expect(screen.getByText("sk-dismiss-me")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /^done$/i }));
    await waitFor(() => expect(container.textContent).not.toMatch(/sk-dismiss-me/));
  });

  it("escapes a hostile key name rather than rendering it as markup", async () => {
    // `name` is operator-supplied and round 2 proved the server stores it verbatim, so the
    // escaping has to happen here.
    mocks.list.mockResolvedValue({ keys: [row({ name: "<img src=x onerror=alert(1)>" })] });
    const { container } = renderCard();
    await waitFor(() => expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy());
    expect(container.querySelector("img")).toBeNull();
  });

  it("does not leave the key in the form input after issuing", async () => {
    mocks.create.mockResolvedValue({ ...row(), key: "sk-not-in-the-box" });
    renderCard();
    await waitFor(() => expect(mocks.list).toHaveBeenCalled());
    const input = screen.getByLabelText("Key name") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ci" } });
    fireEvent.click(screen.getByRole("button", { name: /create key/i }));
    await waitFor(() => expect(screen.getByText("sk-not-in-the-box")).toBeTruthy());
    expect(input.value).toBe("");
  });
});
