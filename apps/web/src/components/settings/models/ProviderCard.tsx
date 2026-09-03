import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

import { api, type Provider } from "../../../api/client";
import { apiErrorDetail, isLoopbackUrl, providerLabel } from "../../../lib/models";

/** `ok` = probed and everything this provider needs to serve is there. `partial` = reachable,
 *  but at least one role's bound model is not (yet) actually served — a real, nameable gap,
 *  not a fabricated "connected" (O5). `error` = unreachable / rejected. */
type Probe = { state: "ok" | "partial" | "error"; msg: string };
type TestResult = Probe | null;

function classify(
  res: { ok: boolean; count: number; models: string[]; error?: string },
  boundModels: string[],
): Probe {
  if (!res.ok) return { state: "error", msg: res.error ?? "unreachable" };
  const missing = boundModels.filter((m) => m && !res.models.includes(m));
  if (missing.length > 0) {
    return { state: "partial", msg: `missing ${missing.join(", ")}` };
  }
  return { state: "ok", msg: res.count === 1 ? "1 model" : `${res.count} models` };
}

/** One provider connection. A hosted provider shows a truthful status dot (connected /
 *  error only after an actual test; otherwise just whether a key is saved) and expands
 *  to a minimal inline connect form — base URL, API key, Test connection. Keys are
 *  write-only; never shown back.
 *
 *  A LOCAL provider (Ollama) used to render an unconditional "always on" green dot —
 *  never actually probed (O5). It is now probed the same way: once on mount (so the
 *  card is truthful without a click) and again on Test, via the SAME POST
 *  /providers/test the hosted path uses (its local branch, #119/M1). */
export function ProviderCard({
  provider,
  boundModels = [],
}: {
  provider: Provider;
  /** Models a role currently binds to this provider — lets a probe distinguish "reachable and
   *  ready" from "reachable but missing what a role needs" (amber, not green). Optional so an
   *  existing caller that hasn't threaded it through yet still compiles; absent, the dot never
   *  reads `partial`. */
  boundModels?: string[];
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? "");
  const [onBox, setOnBox] = useState(provider.on_box);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<TestResult>(null);
  const [saving, setSaving] = useState(false);

  // Probe a local provider once on mount — the card's dot is otherwise a claim about a
  // server nobody asked. Not re-probed on every render; `test()` (the manual "re-check")
  // and a fresh mount are the two triggers, mirroring the hosted card's own discipline
  // (no polling a provider's API on every render either).
  useEffect(() => {
    if (!provider.local) return;
    let cancelled = false;
    void api.testProvider(provider.id).then(
      (res) => {
        if (!cancelled) setResult(classify(res, boundModels));
      },
      () => {
        if (!cancelled) setResult({ state: "error", msg: "unreachable" });
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- probe once per mounted card
  }, [provider.id, provider.local]);

  const dot = statusDot(provider, result);
  // On-box is only meaningful for a loopback endpoint (a forwarding proxy also binds to
  // loopback, so the declaration is the second, deliberate half — see ADR-0024). The
  // server enforces this; disabling here just makes the rule visible.
  const loopback = isLoopbackUrl(baseUrl);

  async function test() {
    setTesting(true);
    setResult(null);
    try {
      const res = await api.testProvider(provider.id, apiKey.trim() || undefined, baseUrl.trim() || undefined);
      const classified = classify(res, boundModels);
      // A manual "Test connection" click keeps its own established wording ("N models loaded");
      // the mount/re-check probe (below) uses the shorter "N models" for the compact dot label.
      setResult(
        classified.state === "ok"
          ? { state: "ok", msg: `${res.count} models loaded` }
          : classified,
      );
    } catch (e) {
      setResult({ state: "error", msg: apiErrorDetail(e) });
    } finally {
      setTesting(false);
    }
  }

  async function save() {
    setSaving(true);
    try {
      // Send the EFFECTIVE flag: repointing at a hosted URL clears the declaration rather
      // than tripping the server's 422, so "untick + repoint" is one honest save.
      const entry: { api_key?: string; base_url?: string; on_box?: boolean } = {
        base_url: baseUrl.trim(),
        on_box: onBox && loopback,
      };
      if (apiKey.trim()) entry.api_key = apiKey.trim();
      await api.saveProviders({ providers: { [provider.id]: entry } });
      await qc.invalidateQueries({ queryKey: ["providers"] });
      await qc.invalidateQueries({ queryKey: ["models"] });
      setApiKey("");
      toast({ title: "Saved", variant: "success" });
    } catch (e) {
      toast({ title: "Couldn't save", description: apiErrorDetail(e), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg bg-card p-3 ring-1 ring-white/12">
      <div className="flex items-center gap-2">
        <span className={cn("size-2 shrink-0 rounded-full", dot.cls)} aria-hidden />
        <span className="flex-1 text-sm font-medium">{providerLabel(provider.id)}</span>
        {provider.local ? (
          <span className="flex items-center gap-1.5">
            <span className="font-mono text-[10px] text-muted-foreground">local · $0</span>
            <button
              type="button"
              onClick={() => void test()}
              disabled={testing}
              className="rounded border-0 bg-transparent px-1 py-0.5 font-mono text-[10px] text-primary hover:underline disabled:opacity-50"
            >
              {testing ? "checking…" : "re-check"}
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="rounded border-0 bg-transparent px-1.5 py-0.5 font-mono text-[11px] text-primary hover:underline"
          >
            {open ? "close" : provider.configured ? "edit" : "connect"}
          </button>
        )}
      </div>
      <span className="pl-4 font-mono text-[10px] text-muted-foreground/70">{dot.label}</span>

      {!provider.local && open && (
        <div className="mt-1 flex flex-col gap-2 border-t border-border/40 pt-2">
          <Input
            type="password"
            aria-label={`${provider.id} API key`}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={
              provider.has_key
                ? `saved ${provider.key_masked} — leave blank to keep`
                : provider.uses_env_key
                  ? `using ${provider.env_key} from environment`
                  : `${provider.env_key ?? "API"} key`
            }
            className="h-8 font-mono text-xs"
          />
          <Input
            aria-label={`${provider.id} base URL`}
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="base URL (optional — OpenAI-compatible endpoints)"
            className="h-8 font-mono text-xs"
          />
          <label
            className={cn(
              "flex items-start gap-2 text-[11px] leading-snug",
              loopback ? "text-muted-foreground" : "text-muted-foreground/50",
            )}
          >
            <input
              type="checkbox"
              className="mt-0.5 size-3 shrink-0"
              checked={onBox && loopback}
              disabled={!loopback}
              onChange={(e) => setOnBox(e.target.checked)}
              aria-label={`${provider.id} runs on this machine`}
            />
            <span>
              Runs on this machine — exempt from cloud-egress consent.
              {loopback
                ? " Only tick this if the endpoint itself does the inference; a proxy that forwards to a hosted API is still off-box."
                : " Needs a loopback base URL (e.g. http://localhost:8001/v1)."}
            </span>
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" className="h-7" disabled={testing} onClick={() => void test()}>
              {testing ? "Testing…" : "Test connection"}
            </Button>
            <Button size="sm" className="h-7" disabled={saving} onClick={() => void save()}>
              {saving ? "Saving…" : "Save"}
            </Button>
            {result && (
              <span
                className={cn(
                  "font-mono text-[11px]",
                  result.state === "ok"
                    ? "text-success"
                    : result.state === "partial"
                      ? "text-amber-600 dark:text-amber-400"
                      : "text-destructive",
                )}
              >
                {`${result.state === "ok" ? "✓" : result.state === "partial" ? "⚠" : "✗"} ${result.msg}`}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** The status dot + label from real state (O5): green only after a probe reports OK, red
 *  when it reports unreachable, amber when reachable but missing something a role needs
 *  (or — hosted, pre-probe — a saved but untested key), grey when nothing has probed it
 *  yet. Never an unconditional "always on" — a local provider is probed exactly like a
 *  hosted one (`POST /providers/test`'s local branch), just automatically on mount. */
function statusDot(provider: Provider, result: TestResult): { cls: string; label: string } {
  if (result) {
    if (result.state === "ok") return { cls: "bg-success", label: `connected · ${result.msg}` };
    if (result.state === "partial") return { cls: "bg-amber-500", label: `reachable · ${result.msg}` };
    return { cls: "bg-destructive", label: `error · ${result.msg}` };
  }
  if (provider.local) return { cls: "bg-muted-foreground/40", label: "checking…" };
  if (provider.uses_env_key) return { cls: "bg-success/70", label: `key from ${provider.env_key}` };
  if (provider.has_key) return { cls: "bg-amber-500", label: `key saved ${provider.key_masked} · untested` };
  return { cls: "bg-muted-foreground/40", label: "no key — not connected" };
}
