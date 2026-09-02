import { AlertTriangle, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
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

import { api, type CostModeRole, type ModelSource, type Pricing, type RoleBinding, type RoleMeta } from "../../../api/client";
import { priceChip, providerLabel, roleNeedsTools, roleWarning } from "../../../lib/models";
import { TONE_BADGE } from "../../StatusBadge";

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
  pricing,
  localProviderIds,
  onChange,
  onReset,
}: {
  meta: RoleMeta;
  cell: CostModeRole | undefined;
  sources: ModelSource[];
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

  // Re-sync from the server once no edit is pending (e.g. after a save/reset refetch).
  useEffect(() => {
    if (phase === "clean") {
      setProvider(effProvider);
      setModel(effModel);
    }
  }, [effProvider, effModel, phase]);

  // model → provider, so a single picker recovers the provider from the choice.
  const modelProvider = new Map<string, string>();
  for (const s of sources) {
    const pid = s.source.toLowerCase();
    for (const m of s.models) if (!modelProvider.has(m)) modelProvider.set(m, pid);
  }
  const known = modelProvider.has(model);

  const isLocal = localProviderIds.has(provider);
  const needsTools = roleNeedsTools(meta.role);
  const price = priceChip(model, isLocal, pricing);
  const warn = roleWarning(provider, model, isLocal, pricing);
  const pending = phase !== "clean";

  function pick(m: string) {
    const pid = modelProvider.get(m) ?? provider;
    setProvider(pid);
    setModel(m);
    setErr(null);
    setPhase(m === effModel && pid === effProvider ? "clean" : "dirty");
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
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  function save() {
    setPhase("saving");
    onChange({ provider, model });
    setPhase("clean"); // optimistic; the poll refetch is authoritative
  }

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
          {sources.map((src) =>
            src.models.length === 0 ? null : (
              <SelectGroup key={src.source}>
                <SelectLabel>{providerLabel(src.source.toLowerCase())}</SelectLabel>
                {src.models.map((m) => (
                  <SelectItem key={m} value={m} className="font-mono text-xs">
                    {m}
                  </SelectItem>
                ))}
              </SelectGroup>
            ),
          )}
        </SelectContent>
      </Select>

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
        <p className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-300 lg:col-span-3">
          <AlertTriangle className="size-3.5 shrink-0" />
          <span>{err ?? warn}</span>
          {!err && price.tone === "unknown" && (
            <a href="#models-pricing" className="font-medium underline underline-offset-2">
              Add price
            </a>
          )}
        </p>
      )}
    </div>
  );
}
