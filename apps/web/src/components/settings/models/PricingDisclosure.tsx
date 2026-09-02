import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
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
import { useToast } from "@/components/ui/toast";

import { api, type ModelSource, type Pricing, type PriceEntry } from "../../../api/client";
import { ConsoleLabel } from "../../overview/bits";

interface Row {
  model: string;
  input: string;
  output: string;
  cacheWrite: string;
  cacheRead: string;
}

/** Pricing, tucked behind a disclosure — hidden until a hosted provider exists,
 *  since local models are free. Per paid model: $/1M input & output tokens, used to
 *  price runs. Also the jump target (#models-pricing) for a role row's "Add price"
 *  fix, so it opens when linked to. */
export function PricingDisclosure({ pricing, sources }: { pricing: Pricing; sources: ModelSource[] }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setRows(
      Object.entries(pricing.prices).map(([model, r]) => ({
        model,
        input: String(r.input),
        output: String(r.output),
        cacheWrite: r.cache_write == null ? "" : String(r.cache_write),
        cacheRead: r.cache_read == null ? "" : String(r.cache_read),
      })),
    );
  }, [pricing]);

  // Open when a role row's "Add price" link jumps here.
  useEffect(() => {
    const sync = () => {
      if (window.location.hash === "#models-pricing") setOpen(true);
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const allModels = sources.flatMap((s) => s.models);
  const setRow = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const addRow = () =>
    setRows((rs) => [...rs, { model: "", input: "", output: "", cacheWrite: "", cacheRead: "" }]);
  const removeRow = (i: number) => setRows((rs) => rs.filter((_, j) => j !== i));

  async function save() {
    setSaving(true);
    const prices: Record<string, PriceEntry> = {};
    for (const r of rows) {
      const model = r.model.trim();
      const input = Number(r.input);
      const output = Number(r.output);
      if (!model || Number.isNaN(input) || Number.isNaN(output) || input < 0 || output < 0) continue;
      // Cache rates travel only as a COMPLETE pair: a half-filled pair would persist as a
      // 3-element entry, which the parser drops whole — leaving the model with no price at all.
      const cw = r.cacheWrite.trim() === "" ? null : Number(r.cacheWrite);
      const cr = r.cacheRead.trim() === "" ? null : Number(r.cacheRead);
      const cacheOk =
        cw != null && cr != null && !Number.isNaN(cw) && !Number.isNaN(cr) && cw >= 0 && cr >= 0;
      prices[model] = cacheOk
        ? { input, output, cache_write: cw, cache_read: cr }
        : { input, output };
    }
    try {
      await api.savePricing(prices);
      await qc.invalidateQueries({ queryKey: ["pricing"] });
      await qc.invalidateQueries({ queryKey: ["project-cost"] });
      toast({ title: "Saved", variant: "success" });
    } catch (e) {
      toast({ title: "Couldn't save", description: e instanceof Error ? e.message : String(e), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  const count = Object.keys(pricing.prices).length;

  return (
    <section id="models-pricing" aria-label="Pricing" className="scroll-mt-20">
      <details open={open} className="group">
        <summary
          onClick={(e) => {
            e.preventDefault();
            setOpen((v) => !v);
          }}
          className="flex w-fit cursor-pointer list-none items-center gap-1.5 text-sm font-medium hover:text-foreground [&::-webkit-details-marker]:hidden"
        >
          <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
          Pricing
          <span className="font-mono text-xs font-normal text-muted-foreground">
            · {count} paid {count === 1 ? "model" : "models"}
          </span>
        </summary>

        <div className="mt-3 flex flex-col gap-3">
          <p className="max-w-2xl text-xs leading-relaxed text-muted-foreground/80">
            API cost per model, in dollars per 1M tokens. Applies to new runs; historical costs
            keep their computed rate. Pricing a LOCAL model costs you nothing and bills nothing —
            it is how you see what a run would have cost on a hosted model, shown on the record as
            &ldquo;shadow&rdquo; spend. Cache rates are optional and travel as a PAIR: set both and
            a cached run is priced with the real discount (a hit is ~0.1x input); leave both blank
            and cache tokens price at the input rate, which OVERSTATES a cached run.
          </p>

          <div className="flex flex-col gap-2">
            <div className="grid grid-cols-[1fr_5rem_5rem_5rem_5rem_2rem] items-center gap-2 px-0.5">
              <ConsoleLabel>Model</ConsoleLabel>
              <ConsoleLabel>In $/M</ConsoleLabel>
              <ConsoleLabel>Out $/M</ConsoleLabel>
              <ConsoleLabel>Cache W</ConsoleLabel>
              <ConsoleLabel>Cache R</ConsoleLabel>
              <span />
            </div>
            {rows.length === 0 && (
              <p className="px-0.5 text-xs text-muted-foreground/60">
                No priced models yet — add one for each paid model you route to.
              </p>
            )}
            {rows.map((r, i) => {
              const taken = new Set(rows.filter((_, j) => j !== i).map((x) => x.model));
              const missing = r.model && !allModels.includes(r.model);
              return (
                <div
                  key={i}
                  className="grid grid-cols-[1fr_5rem_5rem_5rem_5rem_2rem] items-center gap-2"
                >
                  <Select value={r.model || null} onValueChange={(v) => setRow(i, { model: v ?? "" })}>
                    <SelectTrigger aria-label={`model ${i + 1}`} className="h-8 font-mono text-xs">
                      <SelectValue placeholder="Select a model…" />
                    </SelectTrigger>
                    <SelectContent>
                      {missing && (
                        <SelectItem value={r.model} className="font-mono text-xs">
                          {r.model} (not installed)
                        </SelectItem>
                      )}
                      {sources.map((src) => {
                        const options = src.models.filter((m) => !taken.has(m));
                        if (options.length === 0) return null;
                        return (
                          <SelectGroup key={src.source}>
                            <SelectLabel>{src.source}</SelectLabel>
                            {options.map((m) => (
                              <SelectItem key={m} value={m} className="font-mono text-xs">
                                {m}
                              </SelectItem>
                            ))}
                          </SelectGroup>
                        );
                      })}
                    </SelectContent>
                  </Select>
                  <Input
                    aria-label={`input rate ${i + 1}`}
                    value={r.input}
                    onChange={(e) => setRow(i, { input: e.target.value })}
                    inputMode="decimal"
                    placeholder="3.0"
                    className="h-8 font-mono text-xs"
                  />
                  <Input
                    aria-label={`output rate ${i + 1}`}
                    value={r.output}
                    onChange={(e) => setRow(i, { output: e.target.value })}
                    inputMode="decimal"
                    placeholder="15.0"
                    className="h-8 font-mono text-xs"
                  />
                  <Input
                    aria-label={`cache write rate ${i + 1}`}
                    value={r.cacheWrite}
                    onChange={(e) => setRow(i, { cacheWrite: e.target.value })}
                    inputMode="decimal"
                    placeholder="1.25"
                    className="h-8 font-mono text-xs"
                  />
                  <Input
                    aria-label={`cache read rate ${i + 1}`}
                    value={r.cacheRead}
                    onChange={(e) => setRow(i, { cacheRead: e.target.value })}
                    inputMode="decimal"
                    placeholder="0.10"
                    className="h-8 font-mono text-xs"
                  />
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={`remove ${r.model || i + 1}`}
                    onClick={() => removeRow(i)}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 />
                  </Button>
                </div>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={addRow}>
              <Plus data-icon="inline-start" />
              Add model
            </Button>
            <Button size="sm" onClick={() => void save()} disabled={saving}>
              {saving ? "Saving…" : "Save prices"}
            </Button>
          </div>
        </div>
      </details>
    </section>
  );
}
