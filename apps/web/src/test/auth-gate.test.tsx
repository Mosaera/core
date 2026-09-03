import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthStatus } from "../api/auth";
import { AuthProvider } from "../api/authContext";
import { AuthGate } from "../components/AuthGate";

const status = vi.fn();
const login = vi.fn();
/** #119: the gate now also asks whether this instance can RUN anything. Ready by default here —
 *  the first-run wizard has its own suite; these tests are about authentication. */
const preflight = vi.fn(async () => ({
    checks: [],
    inventory: {
        ollama_reachable: true,
        ollama_tags: ["m"],
        ollama_error: "",
        env_keys: [],
    },
    can_run: true,
    reason: "",
}));

vi.mock("../api/firstRun", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/firstRun")>();
    return {
        ...mod,
        firstRunApi: { ...mod.firstRunApi, preflight: () => preflight() },
    };
});

vi.mock("../api/auth", () => ({
    subscribe: () => () => {},
    authApi: {
        status: () => status(),
        login: (u: string, p: string) => login(u, p),
        logout: () => Promise.resolve(),
    },
}));

function snap(over: Partial<AuthStatus> = {}): AuthStatus {
    return {
        users_supported: true,
        needs_setup: false,
        auth_required: true,
        user: null,
        ...over,
    };
}

function renderGate() {
    return render(
        <QueryClientProvider
            client={
                new QueryClient({
                    defaultOptions: { queries: { retry: false } },
                })
            }
        >
            <AuthProvider>
                <AuthGate>
                    <div>APP CONTENT</div>
                </AuthGate>
            </AuthProvider>
        </QueryClientProvider>,
    );
}

beforeEach(() => {
    status.mockReset();
    login.mockReset();
});

describe("AuthGate", () => {
    it("renders the app when a user is signed in", async () => {
        status.mockResolvedValue(
            snap({ user: { id: 1, username: "alex", is_admin: true } }),
        );
        renderGate();
        expect(await screen.findByText("APP CONTENT")).toBeInTheDocument();
    });

    it("renders the app on an unconfigured (open) box", async () => {
        status.mockResolvedValue(
            snap({ auth_required: false, needs_setup: false }),
        );
        renderGate();
        expect(await screen.findByText("APP CONTENT")).toBeInTheDocument();
    });

    it("names the command instead of offering a door with no key behind it", async () => {
        // A database, no accounts, auth enforced. Nothing typed into a login form can succeed here —
        // the first administrator is created by `mosaera-setup`, in a terminal (ADR-0116) — so the
        // screen says that rather than presenting a form that cannot work.
        status.mockResolvedValue(
            snap({ needs_setup: true, auth_required: true }),
        );
        renderGate();

        expect(
            await screen.findByText("This instance has no accounts yet."),
        ).toBeInTheDocument();
        expect(screen.getByText("uv run mosaera-setup")).toBeInTheDocument();
        expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
        expect(screen.queryByLabelText("Setup token")).not.toBeInTheDocument();
        expect(screen.queryByText("APP CONTENT")).not.toBeInTheDocument();
    });

    it("has no browser route that creates an account", async () => {
        // The whole of the CWE-1188 fix: the unauthenticated first-admin race needed an endpoint that
        // mints an admin, and the client no longer has one to call.
        const { authApi } = await import("../api/auth");
        expect("setup" in authApi).toBe(false);
    });

    it("shows the login form and surfaces a bad-credential error", async () => {
        status.mockResolvedValue(
            snap({ auth_required: true, needs_setup: false }),
        );
        login.mockResolvedValue({
            ok: false,
            json: () =>
                Promise.resolve({ detail: "invalid username or password" }),
        });
        renderGate();
        expect(
            await screen.findByText("Enter the governed workspace."),
        ).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("Username"), {
            target: { value: "alex" },
        });
        fireEvent.change(screen.getByLabelText("Password"), {
            target: { value: "nope1234" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Login" }));
        expect(
            await screen.findByText("Invalid username or password."),
        ).toBeInTheDocument();
        // Still gated (no app).
        expect(screen.queryByText("APP CONTENT")).not.toBeInTheDocument();
    });
});
