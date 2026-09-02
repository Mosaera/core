import { ChevronRight } from "lucide-react";
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

import { type ProvidersState, type RoleBinding } from "../../../api/client";
import { providerLabel } from "../../../lib/models";
import { ConsoleLabel } from "../../overview/bits";

/** The base role bindings — the fallback every preset inherits when it doesn't
 *  override a role. Demoted into a disclosure because most tuning happens per-preset
 *  in the table above; this is the safety net. A single model picker per role
 *  (provider derived from the choice); nothing persists until Save defaults. */
export function RoleDefaultsDisclosure({
  providers,
  onSave,
}: {
  providers: ProvidersState;
  onSave: (roles: Record<string, RoleBinding>) => void;
}) {
  const [draft, setDraft] = useState<Record<string, RoleBinding>>(providers.roles);
  const [dirty, setDirty] = useState(false);

  // Re-seed from the server when it changes and no edit is pending.
  useEffect(() => {
    if (!dirty) setDraft(providers.roles);
  }, [providers.roles, dirty]);

  // model → provider, so a single picker recovers the provider from the choice.
  const modelProvider = new Map<string, string>();
  for (const s of providers.sources) {
    const pid = s.source.toLowerCase();
    for (const m of s.models) if (!modelProvider.has(m)) modelProvider.set(m, pid);
  }

  function pick(role: string, model: string) {
    const current = draft[role];
    const provider = modelProvider.get(model) ?? current?.provider ?? "ollama";
    setDraft((d) => ({ ...d, [role]: { provider, model } }));
    setDirty(true);
  }

  function save() {
    onSave(draft);
    setDirty(false);
  }

  return (
    <details className="group mt-2 border-t border-border/40 pt-3">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
        Role defaults (fallback)
      </summary>

      <div className="mt-3 flex flex-col gap-2">
        <p className="max-w-2xl text-xs leading-relaxed text-muted-foreground/80">
          The model each role uses when the active preset doesn't override it. Keep everything on
          local Ollama, or set a stronger default per role.
        </p>
        <div className="grid grid-cols-[8rem_minmax(0,1fr)] items-center gap-2 px-0.5">
          <ConsoleLabel>Role</ConsoleLabel>
          <ConsoleLabel>Model</ConsoleLabel>
        </div>
        {providers.role_meta.map((m) => {
          const binding = draft[m.role];
          const model = binding?.model ?? "";
          const known = modelProvider.has(model);
          return (
            <div key={m.role} className="grid grid-cols-[8rem_minmax(0,1fr)] items-center gap-2">
              <span className="font-mono text-xs uppercase text-muted-foreground" title={m.remit}>
                {m.role}
              </span>
              <Select value={model || null} onValueChange={(v) => pick(m.role, v ?? "")}>
                <SelectTrigger aria-label={`${m.role} default model`} className="h-8 font-mono text-xs">
                  <SelectValue placeholder="Select a model…" />
                </SelectTrigger>
                <SelectContent>
                  {!known && model && (
                    <SelectItem value={model} className="font-mono text-xs">
                      {model} (custom)
                    </SelectItem>
                  )}
                  {providers.sources.map((src) =>
                    src.models.length === 0 ? null : (
                      <SelectGroup key={src.source}>
                        <SelectLabel>{providerLabel(src.source.toLowerCase())}</SelectLabel>
                        {src.models.map((mm) => (
                          <SelectItem key={mm} value={mm} className="font-mono text-xs">
                            {mm}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    ),
                  )}
                </SelectContent>
              </Select>
            </div>
          );
        })}
        {dirty && (
          <Button size="sm" className="mt-1 self-start" onClick={save}>
            Save defaults
          </Button>
        )}
      </div>
    </details>
  );
}
