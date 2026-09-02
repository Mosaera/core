import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

import { api, type Provider } from "../../../api/client";
import { isLoopbackUrl, providerLabel } from "../../../lib/models";

type TestResult = { ok: boolean; msg: string } | null;

/** One provider connection. Ollama is always-on and local; a hosted provider shows
 *  a truthful status dot (connected / error only after an actual test; otherwise
 *  just whether a key is saved) and expands to a minimal inline connect form —
 *  base URL, API key, Test connection. Keys are write-only; never shown back. */
export function ProviderCard({ provider }: { provider: Provider }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? "");
  const [onBox, setOnBox] = useState(provider.on_box);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<TestResult>(null);
  const [saving, setSaving] = useState(false);

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
      setResult(
        res.ok
          ? { ok: true, msg: `${res.count} models loaded` }
          : { ok: false, msg: res.error ?? "test failed" },
      );
    } catch (e) {
      setResult({ ok: false, msg: e instanceof Error ? e.message : String(e) });
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
      toast({ title: "Couldn't save", description: e instanceof Error ? e.message : String(e), variant: "error" });
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
          <span className="font-mono text-[10px] text-muted-foreground">local · $0</span>
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
              <span className={cn("font-mono text-[11px]", result.ok ? "text-success" : "text-destructive")}>
                {`${result.ok ? "✓" : "✗"} ${result.msg}`}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** The status dot + label from real state: connected/error only after an actual
 *  test (no persisted health exists); otherwise whether a key is saved. */
function statusDot(provider: Provider, result: TestResult): { cls: string; label: string } {
  if (provider.local) return { cls: "bg-success", label: "always on" };
  if (result) {
    return result.ok
      ? { cls: "bg-success", label: `connected · ${result.msg}` }
      : { cls: "bg-destructive", label: `error · ${result.msg}` };
  }
  if (provider.uses_env_key) return { cls: "bg-success/70", label: `key from ${provider.env_key}` };
  if (provider.has_key) return { cls: "bg-amber-500", label: `key saved ${provider.key_masked} · untested` };
  return { cls: "bg-muted-foreground/40", label: "no key — not connected" };
}
