import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";

import { authApi } from "@/api/auth";
import { useAuth } from "@/api/authContext";

import loginBackground from "../assets/app-background.webp";

/**
 * Gates the application behind authentication.
 *
 * Renders:
 * - The application once the user is authenticated.
 * - The application immediately on an unconfigured loopback instance.
 * - A login screen when authentication is required.
 * - A sentence naming `mosaera-setup` when the instance has no accounts at all.
 *
 * THE BROWSER NO LONGER CREATES ACCOUNTS (ADR-0116). Setup is a terminal wizard, because only
 * Postgres is containerised — the API runs on the host — so every install already happens at a
 * terminal, and a browser cannot install Docker, start Postgres or write `.env` even in principle.
 * What is left here is the one thing a browser is for: signing in.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
    const { loading, status, user, refresh } = useAuth();

    if (loading || !status) {
        return (
            <div className="flex min-h-svh items-center justify-center bg-background text-sm text-muted-foreground">
                Connecting…
            </div>
        );
    }

    if (user || !status.auth_required) {
        return <>{children}</>;
    }

    // A database, no accounts, and auth enforced. A login form here is a door with no key behind it —
    // the dead end ADR-0116 §8 exists about — so say what actually opens it.
    if (status.needs_setup) {
        return <NoAccountsYet />;
    }

    return <CredentialForm onDone={refresh} />;
}

const COPY = {
    description: "Enter the governed workspace.",
    usernameAutocomplete: "username",
    passwordAutocomplete: "current-password",
} as const;

type FailedAttempt = {
    username: string;
    password: string;
};

/**
 * A database, no accounts, and authentication enforced. Nothing typed into a login form can
 * succeed here, so this does not offer one — it names the command that creates the account.
 */
function NoAccountsYet() {
    return (
        <Backdrop>
            <Wordmark />

            <p className="mt-4 text-center text-sm text-white/60">
                This instance has no accounts yet.
            </p>

            <p className="mt-6 text-center text-sm text-white/45">
                Create the first administrator on the machine that runs Mosaera:
            </p>

            <pre className="mt-3 overflow-x-auto rounded-lg border border-white/15 bg-black/30 px-4 py-3 text-center font-mono text-sm text-white/80 backdrop-blur-[4px]">
                uv run mosaera-setup
            </pre>

            <p className="mt-4 text-center text-xs text-white/35">
                Setup needs the host — it installs prerequisites, starts the
                database and writes configuration, none of which a browser can
                do. Reload this page once it finishes.
            </p>
        </Backdrop>
    );
}

function Wordmark() {
    return (
        <div className="flex items-center justify-center font-sans">
            <span className="text-[30px] font-extrabold uppercase leading-none tracking-[0.18em] text-white sm:text-[46px]">
                MOS<span className="text-primary">Æ</span>RA
            </span>
        </div>
    );
}

function formatError(message?: string) {
    const fallback = "Invalid username or password.";

    if (!message) {
        return fallback;
    }

    const cleaned = message.trim();

    if (!cleaned) {
        return fallback;
    }

    const normalized = cleaned.charAt(0).toUpperCase() + cleaned.slice(1);

    return normalized.endsWith(".") ? normalized : `${normalized}.`;
}

function Spinner() {
    return (
        <span
            aria-hidden
            className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
        />
    );
}

function ErrorToast({ message }: { message: string }) {
    return (
        <div className="fixed right-4 top-4 z-50 sm:right-5 sm:top-5">
            <div
                role="alert"
                aria-live="assertive"
                className={[
                    "inline-flex max-w-[calc(100vw-2rem)] items-center gap-2",
                    "rounded-md border border-[#A72D3C]/65",
                    "bg-[#1B1216]/95 px-3 py-2",
                    "text-sm text-white/90",
                    "shadow-[0_10px_30px_rgba(0,0,0,0.34)]",
                    "backdrop-blur-md",
                ].join(" ")}
            >
                <span
                    aria-hidden
                    className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#C85B62]"
                />

                <span className="whitespace-nowrap">{message}</span>
            </div>
        </div>
    );
}

function CredentialForm({ onDone }: { onDone: () => void }) {
    const copy = COPY;

    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [toastOpen, setToastOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [failedAttempt, setFailedAttempt] = useState<FailedAttempt | null>(
        null,
    );

    useEffect(() => {
        if (!toastOpen) {
            return;
        }

        const timeout = window.setTimeout(() => {
            setToastOpen(false);
        }, 3000);

        return () => {
            window.clearTimeout(timeout);
        };
    }, [toastOpen]);

    const cleanUsername = username.trim();

    const credentialsChanged =
        failedAttempt === null ||
        cleanUsername !== failedAttempt.username ||
        password !== failedAttempt.password;

    const submitDisabled =
        busy ||
        !cleanUsername ||
        !password ||
        (Boolean(error) && !credentialsChanged);

    async function submit(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (submitDisabled) {
            return;
        }

        const attemptedCredentials: FailedAttempt = {
            username: cleanUsername,
            password,
        };

        setError(null);
        setToastOpen(false);
        setBusy(true);

        try {
            const response = await authApi.login(cleanUsername, password);

            if (response.ok) {
                onDone();
                return;
            }

            const body = (await response.json().catch(() => null)) as {
                detail?: string;
            } | null;

            setFailedAttempt(attemptedCredentials);
            setError(formatError(body?.detail));
            setToastOpen(true);
        } catch {
            setFailedAttempt(attemptedCredentials);
            setError("Couldn't reach the server. Try again.");
            setToastOpen(true);
        } finally {
            setBusy(false);
        }
    }

    return (
        <Backdrop
            toast={error && toastOpen ? <ErrorToast message={error} /> : null}
        >
            <Wordmark />

            <p className="mt-4 text-center text-sm text-white/60">
                {copy.description}
            </p>

            <form onSubmit={submit} className="mt-5">
                <div
                    className={[
                        "grid w-full gap-0 overflow-hidden rounded-lg",
                        "border bg-black/20",
                        "shadow-[0_16px_50px_rgba(0,0,0,0.28)]",
                        "backdrop-blur-[4px]",
                        "transition-[border-color,box-shadow]",
                        "sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_108px]",
                        error
                            ? [
                                  "border-[#A72D3C]",
                                  "shadow-[0_16px_50px_rgba(0,0,0,0.28),0_0_0_1px_rgba(167,45,60,0.3)]",
                              ].join(" ")
                            : [
                                  "border-white/15",
                                  "focus-within:border-white/35",
                                  "focus-within:shadow-[0_16px_50px_rgba(0,0,0,0.28),0_0_0_1px_rgba(255,255,255,0.08)]",
                              ].join(" "),
                    ].join(" ")}
                >
                    <Input
                        autoFocus
                        autoComplete={copy.usernameAutocomplete}
                        placeholder="Username"
                        value={username}
                        onChange={(event) => setUsername(event.target.value)}
                        aria-label="Username"
                        className={[
                            "!m-0 h-12 min-w-0 w-full",
                            "!rounded-none !border-0",
                            "bg-transparent px-4 text-white",
                            "!shadow-none !outline-none",
                            "placeholder:text-white/40",
                            "focus-visible:!border-0",
                            "focus-visible:!ring-0",
                            "focus-visible:!ring-offset-0",
                            "sm:!border-r sm:!border-r-white/12",
                        ].join(" ")}
                    />

                    <Input
                        type="password"
                        autoComplete={copy.passwordAutocomplete}
                        placeholder="Password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        aria-label="Password"
                        className={[
                            "!m-0 h-12 min-w-0 w-full",
                            "!rounded-none !border-0",
                            "border-t !border-t-white/12",
                            "bg-transparent px-4 text-white",
                            "!shadow-none !outline-none",
                            "placeholder:text-white/40",
                            "focus-visible:!border-0",
                            "focus-visible:!ring-0",
                            "focus-visible:!ring-offset-0",
                            "sm:!border-t-0",
                            "sm:!border-r sm:!border-r-white/12",
                        ].join(" ")}
                    />

                    <button
                        type="submit"
                        disabled={submitDisabled}
                        aria-label={busy ? "Logging in" : "Login"}
                        className={[
                            "m-0 flex h-12 w-full shrink-0 appearance-none",
                            "cursor-pointer items-center justify-center",
                            "rounded-none border-0 px-4",
                            "text-sm font-medium text-white",
                            "shadow-none outline-none",
                            "transition-colors",
                            "focus-visible:outline-none",
                            "disabled:cursor-pointer",
                            error && credentialsChanged
                                ? [
                                      "bg-[#A72D3C]/65",
                                      "hover:bg-[#A72D3C]/80",
                                      "focus-visible:bg-[#A72D3C]/80",
                                  ].join(" ")
                                : error
                                  ? [
                                        "bg-[#A72D3C]/20",
                                        "text-white/35",
                                        "disabled:bg-[#A72D3C]/20",
                                        "disabled:text-white/35",
                                    ].join(" ")
                                  : [
                                        "bg-white/12",
                                        "hover:bg-white/18",
                                        "focus-visible:bg-white/18",
                                        "disabled:bg-white/[0.05]",
                                        "disabled:text-white/25",
                                    ].join(" "),
                        ].join(" ")}
                    >
                        {busy ? <Spinner /> : "Login"}
                    </button>
                </div>
            </form>
        </Backdrop>
    );
}

/**
 * The signed-out chrome — one copy, shared by the login form and the no-accounts screen. It was
 * inline in the form; a second screen needing the same background is exactly when that stops being
 * acceptable.
 */
function Backdrop({
    children,
    toast = null,
}: {
    children: React.ReactNode;
    toast?: React.ReactNode;
}) {
    return (
        <main
            className="relative min-h-svh overflow-hidden bg-background bg-cover bg-center"
            style={{ backgroundImage: `url(${loginBackground})` }}
        >
            {toast}

            <div aria-hidden className="absolute inset-0 bg-black/80" />

            <div
                aria-hidden
                className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(20,17,20,0.34)_0%,rgba(20,17,20,0.18)_30%,transparent_62%)]"
            />

            <div
                aria-hidden
                className="absolute inset-0 bg-[linear-gradient(to_bottom,rgba(8,7,8,0.16),transparent_24%,transparent_72%,rgba(8,7,8,0.28))]"
            />

            <section className="relative flex min-h-svh items-center justify-center px-5 py-20 sm:px-8 lg:px-12">
                <div className="w-full max-w-[720px]">{children}</div>
            </section>

            <footer className="absolute inset-x-0 bottom-6 px-6 text-center">
                <p className="text-[11px] font-medium tracking-[0.16em] text-white/35">
                    MOSAERA · GOVERNED EXECUTION
                </p>
            </footer>
        </main>
    );
}
