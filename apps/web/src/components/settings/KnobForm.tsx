import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { useAuth } from "../../api/authContext";
import { api, type KnobValue, type KnobView } from "../../api/client";
import { apiErrorDetail } from "../../lib/models";
import { SettingsSection } from "./SettingsSection";

export interface FieldSpec {
  field: string;
  label: string;
  help?: string;
  // Enumerable values use "select" (dropdown from the knob's server-declared choices),
  // never free text — no typos. Free text ("text") is only for keys/URLs/freeform.
  widget: "number" | "toggle" | "text" | "select";
  unit?: string; // shown before the input, e.g. "$"
  placeholder?: string;
}
export interface KnobGroup {
  title: string;
  fields: FieldSpec[];
}

/** "effort_profile" → "Effort". Derived rather than mapped: the server owns the profile set
 *  (ADR-0122), and a hand-kept label map here would silently miss a profile added later. */
export function profileName(field: string | null): string {
  if (!field) return "";
  const stem = field.replace(/_profile$/, "").replace(/_/g, " ");
  return stem.charAt(0).toUpperCase() + stem.slice(1);
}

/** Sentinel: the raw input text is neither a real value nor an intentional clear — ignore the
 *  keystroke rather than commit it. Exported so `parseFieldInput` is total and testable. */
export const IGNORE = Symbol("ignore-field-input");

/** A text/number input's raw value -> what to stage, or `IGNORE` (S4). A blank field is a
 *  deliberate unset (`null`); a NUMBER field's non-blank text that still fails `Number()` — a
 *  bare "-", "1.2.3", a trailing "e" some browsers let sit in `.value` mid-keystroke — is
 *  NEITHER: committing it as-is would stage garbage, and the old code's `Number(raw)` silently
 *  became `NaN`, which JSON-serializes to `null` and unset the knob without the operator typing
 *  anything that means "clear this". Ignoring it instead leaves the last valid value staged. */
export function parseFieldInput(
  widget: FieldSpec["widget"],
  raw: string,
): KnobValue | typeof IGNORE {
  if (raw === "") return null;
  if (widget !== "number") return raw;
  const n = Number(raw);
  return Number.isNaN(n) ? IGNORE : n;
}

function Toggle({
  on,
  disabled,
  label,
  onChange,
}: {
  on: boolean;
  disabled?: boolean;
  /** The knob's label — a role="switch" with no accessible name is unusable by a screen reader
      and unaddressable by a test; the Select and Input below already carry one. */
  label?: string;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-label={label}
      aria-checked={on}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full border-0 p-0 transition-colors",
        on ? "bg-primary" : "bg-muted",
        disabled ? "opacity-50" : "cursor-pointer",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 size-4 rounded-full bg-background transition-all",
          on ? "left-4" : "left-0.5",
        )}
      />
    </button>
  );
}

function KnobField({
  spec,
  view,
  value,
  editable,
  onChange,
}: {
  spec: FieldSpec;
  view: KnobView | undefined;
  value: KnobValue;
  editable: boolean;
  onChange: (v: KnobValue) => void;
}) {
  const envPinned = view?.source === "env";
  // A conditional clamp: NOT folded into `disabled`. The stored value still governs guided and
  // ad-hoc runs, so the field stays editable — it is the autonomous run where it is overridden,
  // and the operator is told exactly that. Disabling it would swap one lie for another.
  const clampedBy = view?.clamped_by ?? null;
  // ADR-0122 provenance. Two DIFFERENT things to say, and saying only the first would be the
  // more misleading half: a value the profile supplied, and a profile that owns this knob but
  // LOST to an explicit setting. The second is the one an operator hunts for when a profile
  // "did nothing" — without it the override is invisible and the profile looks broken.
  const derivedFrom = view?.derived_from ?? null;
  const fromProfile = derivedFrom !== null && view?.source === "profile";
  const profileOverridden = derivedFrom !== null && view?.source !== "profile";
  const disabled = !editable || envPinned;
  // The server's `choices` is the source of truth for "enumerable → dropdown, never free
  // text" (the Hard Rule): render a Select whenever the knob-view carries choices, even if a
  // FieldSpec forgot widget:"select". Prevents a typo-able text box for a validated enum.
  const asSelect = spec.widget === "select" || (view?.choices?.length ?? 0) > 0;
  return (
    <div className="flex items-center justify-between gap-6 py-4">
      <div className="flex min-w-0 flex-col items-start gap-0.5 pr-4">
        <span className="text-sm font-medium text-foreground">{spec.label}</span>
        {spec.help && (
          <span className="max-w-prose text-[13px] leading-relaxed text-muted-foreground">
            {spec.help}
          </span>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {envPinned && (
          <Badge
            title={`Pinned by ${view?.env}`}
            className="border-transparent bg-muted/60 font-mono text-[9px] uppercase text-muted-foreground"
          >
            set via env
          </Badge>
        )}
        {fromProfile && (
          <Badge
            title={`Derived from your ${profileName(derivedFrom)} profile. Setting this field directly overrides the profile for this knob only.`}
            className="border-transparent bg-primary/10 font-mono text-[9px] uppercase text-primary"
          >
            from {profileName(derivedFrom)}
          </Badge>
        )}
        {profileOverridden && !envPinned && (
          <Badge
            title={`Your ${profileName(derivedFrom)} profile sets this knob, but an explicit value takes precedence. Clear this field to fall back to the profile.`}
            className="border-transparent bg-muted/60 font-mono text-[9px] uppercase text-muted-foreground"
          >
            overrides {profileName(derivedFrom)}
          </Badge>
        )}
        {clampedBy && !envPinned && (
          <Badge
            title={`Forced on for autonomous runs while "${clampedBy}" is enabled — your stored value still applies to guided and ad-hoc runs.`}
            className="border-transparent bg-amber-500/15 font-mono text-[9px] uppercase text-amber-600 dark:text-amber-400"
          >
            forced when autonomous
          </Badge>
        )}
        {spec.widget === "toggle" ? (
          <Toggle
            on={value === true}
            label={spec.label}
            disabled={disabled}
            onChange={(v) => onChange(v)}
          />
        ) : asSelect ? (
          <Select
            value={value === null || value === undefined ? null : String(value)}
            disabled={disabled}
            onValueChange={(v) => onChange(v)}
          >
            <SelectTrigger aria-label={spec.label} className="w-32 text-sm">
              <SelectValue placeholder="—" />
            </SelectTrigger>
            <SelectContent>
              {(view?.choices ?? []).map((c) => (
                <SelectItem key={c} value={c} className="text-sm">
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <div className="flex items-center gap-1">
            {spec.unit && <span className="font-mono text-xs text-muted-foreground">{spec.unit}</span>}
            <Input
              type={spec.widget === "number" ? "number" : "text"}
              disabled={disabled}
              value={value === null || value === undefined ? "" : String(value)}
              placeholder={spec.placeholder ?? (spec.widget === "number" ? "—" : "")}
              onChange={(e) => {
                const next = parseFieldInput(spec.widget, e.target.value);
                if (next !== IGNORE) onChange(next);
              }}
              className="w-28 text-sm"
              aria-label={spec.label}
            />
          </div>
        )}
      </div>
    </div>
  );
}

/** A settings form over a set of operational knobs, driven by GET /settings/general.
 *  Edits are diffed and saved via PUT (admin only); env-pinned fields are read-only. */
export function KnobForm({
  title,
  description,
  groups,
}: {
  title: string;
  description?: string;
  groups: KnobGroup[];
}) {
  const qc = useQueryClient();
  const { isAdmin } = useAuth();
  const { data } = useQuery({ queryKey: ["general-settings"], queryFn: () => api.getGeneralSettings() });
  const [edits, setEdits] = useState<Record<string, KnobValue>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const knobs = data?.knobs ?? {};
  const dirty = Object.keys(edits).length > 0;

  const save = useMutation({
    mutationFn: () => api.saveGeneralSettings(edits),
    onSuccess: (res) => {
      qc.setQueryData(["general-settings"], res);
      const rejected = res.rejected ?? {};
      const fields = Object.keys(rejected);
      if (fields.length > 0) {
        // Honest save semantics (S4/#task-9): a genuinely invalid value already 400s (caught
        // below); this is the field that was silently dropped before — say so instead of
        // reporting "Saved" for a patch that was not entirely applied.
        setEdits((prev) => {
          const kept: Record<string, KnobValue> = {};
          for (const f of fields) if (f in prev) kept[f] = prev[f];
          return kept;
        });
        setError(
          `Not saved — ${fields.map((f) => `${f}: ${rejected[f]}`).join("; ")}`,
        );
      } else {
        setEdits({});
        setError(null);
      }
    },
    onError: (e) => setError(apiErrorDetail(e)),
  });

  const valueOf = (field: string): KnobValue =>
    field in edits ? edits[field] : (knobs[field]?.value ?? null);

  // ADR-0122 §6. The SERVER decides what a knob is; this only decides where it goes. `internal`
  // is dropped outright, `developer` moves behind a disclosure, `core` renders as before. Doing
  // it here rather than by editing the curated field lists means hiding a knob is a one-line
  // server change — and, just as importantly, reversible by the same one line.
  //
  // A field absent from the response is treated as `developer`, not `core`: an unknown knob must
  // not be able to appear in the twelve-control surface by accident.
  const vis = (f: FieldSpec) => knobs[f.field]?.visibility ?? "developer";
  const pick = (want: "core" | "developer") =>
    groups
      .map((g) => ({ ...g, fields: g.fields.filter((f) => vis(f) === want) }))
      .filter((g) => g.fields.length > 0);
  const coreGroups = pick("core");
  const advancedGroups = pick("developer");
  const advancedCount = advancedGroups.reduce((n, g) => n + g.fields.length, 0);

  const renderGroups = (gs: KnobGroup[]) =>
    gs.map((g) => (
      <section key={g.title} className="flex flex-col items-stretch">
        <h3 className="mb-1 text-sm font-semibold text-foreground">{g.title}</h3>
        <div className="flex flex-col items-stretch divide-y divide-border/50">
          {g.fields.map((f) => (
            <KnobField
              key={f.field}
              spec={f}
              view={knobs[f.field]}
              value={valueOf(f.field)}
              editable={isAdmin}
              onChange={(v) => setEdits((prev) => ({ ...prev, [f.field]: v }))}
            />
          ))}
        </div>
      </section>
    ));

  return (
    <SettingsSection
      title={title}
      description={
        description && (
          <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
        )
      }
      action={
        isAdmin && (
          <Button
            size="sm"
            className="shrink-0"
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
          >
            {save.isPending ? "Saving…" : "Save changes"}
          </Button>
        )
      }
    >
      <div className="flex flex-col items-stretch gap-10">
        {renderGroups(coreGroups)}
        {advancedCount > 0 && (
          <div className="flex flex-col items-stretch gap-6 border-t border-border/50 pt-6">
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="self-start text-sm font-medium text-muted-foreground hover:text-foreground"
            >
              {showAdvanced ? "Hide" : "Show"} advanced configuration ({advancedCount})
            </button>
            {showAdvanced && (
              <>
                <p className="max-w-prose text-[13px] leading-relaxed text-muted-foreground">
                  These change how Mosaera reaches the outcome you asked for, rather than what you
                  asked for. The recommended values are the ones already set; incorrect values can
                  reduce reliability or cost control.
                </p>
                {renderGroups(advancedGroups)}
              </>
            )}
          </div>
        )}
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!isAdmin && (
        <p className="text-[11px] text-muted-foreground/70">Read-only — admins can edit these.</p>
      )}
    </SettingsSection>
  );
}
