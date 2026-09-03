import { AlertTriangle, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/CopyButton";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { api, type CostModeRole, type ModelSource, type Pricing, type Provider, type RoleBinding, type RoleMeta } from "../../../api/client";
import {
  apiErrorDetail,
  isNonChatModel,
  ollamaPullFix,
  priceChip,
  providerLabel,
  roleNeedsTools,
  roleWarning,
} from "../../../lib/models";
import { TONE_BADGE } from "../../StatusBadge";

const CUSTOM_VALUE = "__custom__";

const PRICE_TONE = {
  free: TONE_BADGE.success,
  paid: "bg-muted/70 text-muted-foreground",
  unknown: TONE_BADGE.amber,
} as const;

type Phase = "clean" | "dirty" | "testing" | "ready" | "saving" | "failed";

/** One role in the roles table: its job (with the tool requirement inline for the
 *  acting roles), a single model picker grouped by provider (the provider is the
 *  group header, mirroring the pricing selector), and truthful chips. Picking a
 *  model stages a change — nothing persists until you Test it (verifies the model
 *  is actually served by its provider) and the button turns into Save. */
export function RoleRow({
  meta,
  cell,
  sources,
  providers,
  pricing,
  localProviderIds,
  onChange,
  onReset,
}: {
  meta: RoleMeta;
  cell: CostModeRole | undefined;
  sources: ModelSource[];
  /** Full provider connection state, so a hosted model can be badged "needs key" instead of
   *  looking as ready as a configured one (O1-O3). Optional only so existing callers/tests that
   *  don't yet pass it keep compiling — absent, no hosted model is ever badged. */
  providers?: Provider[];
  pricing: Pricing;
  localProviderIds: Set<string>;
  onChange: (binding: RoleBinding) => void;
  onReset: () => void;
}) {
  const effProvider = cell?.effective_provider ?? "";
  const effModel = cell?.effective_model ?? "";
  const overridden = cell?.overridden ?? false;

  const [provider, setProvider] = useState(effProvider);
  const [model, setModel] = useState(effModel);
  const [phase, setPhase] = useState<Phase>("clean");
  const [err, setErr] = useState<string | null>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [customText, setCustomText] = useState("");

  // Re-sync from the server once no edit is pending (e.g. after a save/reset refetch).
  useEffect(() => {
    if (phase === "clean") {
      setProvider(effProvider);
      setModel(effModel);
    }
  }, [effProvider, effModel, phase]);

  // model → provider, so a single picker recovers the provider from the choice. Built from
  // EVERY listed model (not just the chat-filtered ones rendered below) so a role already
  // bound to something unusual is still correctly attributed to its provider.
  const modelProvider = new Map<string, string>();
  const servedModels = new Set<string>();
  for (const s of sources) {
    const pid = s.source.toLowerCase();
    for (const m of s.models) if (!modelProvider.has(m)) modelProvider.set(m, pid);
    for (const m of s.served ?? []) servedModels.add(m);
  }
  const known = modelProvider.has(model);
  const configuredProviders = new Set((providers ?? []).filter((p) => p.configured).map((p) => p.id));

  const isLocal = localProviderIds.has(provider);
  const needsTools = roleNeedsTools(meta.role);
  const price = priceChip(model, isLocal, pricing);
  const warn = roleWarning(provider, model, isLocal, pricing);
  const pending = phase !== "clean";
  // A model listed but not (yet) confirmed usable: not pulled (local) or not verified against a
  // key (hosted). `sources` without a `served` field (an older server) degrades to "don't know",
  // which must NOT be read as "not available" — hence the `sources.some(s => s.served)` guard.
  const anyServedReported = sources.some((s) => s.served !== undefined);
  const notServed = anyServedReported && known && model !== "" && !servedModels.has(model);
  const needsKey = !isLocal && provider !== "" && providers !== undefined && !configuredProviders.has(provider);

  function pick(m: string) {
    if (m === CUSTOM_VALUE) {
      setCustomOpen(true);
      return;
    }
    setCustomOpen(false);
    const pid = modelProvider.get(m) ?? provider;
    setProvider(pid);
    setModel(m);
    setErr(null);
    setPhase(m === effModel && pid === effProvider ? "clean" : "dirty");
  }

  function commitCustom() {
    const m = customText.trim();
    if (!m) return;
    // A free-typed model keeps the CURRENTLY selected provider — there is no name to look it
    // up by, and the Test step is what actually validates the pairing (models.py:53-54: the UI
    // does allow free-text entry, validated by the same test path as a picked one).
    setModel(m);
    setErr(null);
    setPhase(m === effModel ? "clean" : "dirty");
    setCustomOpen(false);
    setCustomText("");
  }

  async function test() {
    setPhase("testing");
    setErr(null);
    try {
      const res = await api.testProvider(provider);
      if (res.ok && res.models.includes(model)) {
        setPhase("ready");
      } else {
        setPhase("failed");
        setErr(res.ok ? `${providerLabel(provider)} doesn't serve this model` : res.error ?? "test failed");
      }
    } catch (e) {
      setPhase("failed");
      setErr(apiErrorDetail(e));
    }
  }

  function save() {
    setPhase("saving");
    onChange({ provider, model });
    setPhase("clean"); // optimistic; the poll refetch is authoritative
  }

  // The failure was specifically "this Ollama model isn't served" (as opposed to the server
  // being unreachable, or a hosted key problem) — that is the one case with an exact fix.
  const pullFix = isLocal && phase === "failed" && err?.includes("doesn't serve this model") ? model : null;

  return (
    <div
      className={cn(
        "flex flex-col gap-2 border-b border-border/50 py-3 last:border-b-0 lg:grid lg:grid-cols-[minmax(11rem,1.3fr)_minmax(0,1.5fr)_minmax(0,1.2fr)] lg:items-center lg:gap-x-4",
        warn && "rounded-md bg-amber-500/[0.06] px-2",
      )}
    >
      {/* Role + one-line job, with the tool requirement inline */}
      <div className="flex min-w-0 flex-col">
        <span className="flex items-center gap-2">
          <span className="text-sm font-medium capitalize">{meta.label}</span>
          {needsTools && (
            <span
              className="rounded-full bg-muted/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
              title="This role acts on the repo, so it needs a tool-calling model."
            >
              needs tools
            </span>
          )}
        </span>
        <span className="truncate text-xs text-muted-foreground" title={meta.remit}>
          {meta.remit}
        </span>
      </div>

      {/* Single model picker, grouped by provider */}
      <div className="flex min-w-0 flex-col gap-1">
        <Select value={model || null} onValueChange={(v) => pick(v ?? "")}>
          <SelectTrigger aria-label={`${meta.role} model`} className="h-8 font-mono text-xs">
            <SelectValue placeholder="Select a model…" />
          </SelectTrigger>
          <SelectContent>
            {!known && model && (
              <SelectItem value={model} className="font-mono text-xs">
                {model} (custom)
              </SelectItem>
            )}
            {sources.map((src) => {
              // Every role here needs a chat/tool-calling model; an embedding model bound to
              // one silently produces nonsense output (O1-O3) — never offer it.
              const served = new Set(src.served ?? []);
              const reportsServed = src.served !== undefined;
              const chatModels = src.models.filter((m) => !isNonChatModel(m));
              const pid = src.source.toLowerCase();
              return chatModels.length === 0 ? null : (
                <SelectGroup key={src.source}>
                  <SelectLabel>{providerLabel(pid)}</SelectLabel>
                  {chatModels.map((m) => {
                    const local = localProviderIds.has(pid);
                    const badge = local
                      ? reportsServed && !served.has(m)
                        ? " — not pulled"
                        : ""
                      : providers !== undefined && !configuredProviders.has(pid)
                        ? " — needs key"
                        : "";
                    return (
                      <SelectItem key={m} value={m} className="font-mono text-xs">
                        {m}
                        {badge}
                      </SelectItem>
                    );
                  })}
                </SelectGroup>
              );
            })}
            <SelectGroup>
              <SelectItem value={CUSTOM_VALUE} className="text-xs italic text-muted-foreground">
                Use a model not listed…
              </SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        {customOpen && (
          <div className="flex items-center gap-1.5">
            <Input
              autoFocus
              aria-label={`${meta.role} custom model id`}
              value={customText}
              onChange={(e) => setCustomText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitCustom();
                if (e.key === "Escape") setCustomOpen(false);
              }}
              placeholder="exact model id — Test will validate it"
              className="h-7 font-mono text-xs"
            />
            <Button size="sm" variant="outline" className="h-7 shrink-0" onClick={commitCustom}>
              Use
            </Button>
          </div>
        )}
      </div>

      {/* Chips + the test/save action */}
      <div className="flex flex-wrap items-center gap-1.5 lg:justify-end">
        <span
          className={cn(
            "rounded-full px-2 py-0.5 font-mono text-[10px]",
            isLocal ? TONE_BADGE.success : "bg-muted/70 text-muted-foreground",
          )}
        >
          {isLocal ? "local" : "cloud"}
        </span>
        <span className={cn("rounded-full px-2 py-0.5 font-mono text-[10px] tabular-nums", PRICE_TONE[price.tone])}>
          {price.text}
        </span>
        {notServed && (
          <span
            className={cn("rounded-full px-2 py-0.5 font-mono text-[10px]", TONE_BADGE.amber)}
            title="Ollama reports this model as not pulled yet."
          >
            not pulled
          </span>
        )}
        {needsKey && (
          <span
            className={cn("rounded-full px-2 py-0.5 font-mono text-[10px]", TONE_BADGE.amber)}
            title="No API key is configured for this provider yet."
          >
            needs key
          </span>
        )}

        {pending ? (
          phase === "ready" ? (
            <Button size="sm" className="h-7 bg-success text-white hover:bg-success/85" onClick={save}>
              Save
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              className="h-7"
              disabled={phase === "testing" || phase === "saving"}
              onClick={() => void test()}
            >
              {phase === "testing" ? "Testing…" : phase === "saving" ? "Saving…" : "Test"}
            </Button>
          )
        ) : overridden ? (
          <button
            type="button"
            onClick={onReset}
            aria-label={`Reset ${meta.role} to default`}
            title="Reset to the preset's default"
            className="flex items-center gap-1 rounded border-0 bg-transparent px-1 py-0.5 font-mono text-[10px] text-muted-foreground/70 hover:text-foreground"
          >
            <RotateCcw className="size-3" />
            reset
          </button>
        ) : (
          <span className="font-mono text-[10px] text-muted-foreground/50">· default</span>
        )}
      </div>

      {/* Amber warning / test failure + one-tap fix (spans the row on wide screens) */}
      {(warn || err) && (
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-amber-700 dark:text-amber-300 lg:col-span-3">
          <AlertTriangle className="size-3.5 shrink-0" />
          <span>{err ?? warn}</span>
          {!err && price.tone === "unknown" && (
            <a href="#models-pricing" className="font-medium underline underline-offset-2">
              Add price
            </a>
          )}
          {pullFix && (
            <>
              <code className="rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[10.5px] text-foreground/90">
                {ollamaPullFix(pullFix)}
              </code>
              <CopyButton text={ollamaPullFix(pullFix)} label="Copy the fix" />
              <button
                type="button"
                onClick={() => void test()}
                className="font-medium underline underline-offset-2"
              >
                Re-check
              </button>
            </>
          )}
        </p>
      )}
    </div>
  );
}
