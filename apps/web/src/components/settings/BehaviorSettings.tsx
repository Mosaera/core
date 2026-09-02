import { useQuery } from "@tanstack/react-query";

import { api, type KnobValue, type KnobView } from "../../api/client";
import { KnobForm, type KnobGroup, profileName } from "./KnobForm";
import { SettingsSection } from "./SettingsSection";

// The intent surface (ADR-0122): the operator states how hard to try and how high the bar is,
// and the SERVER derives the individual knobs. Every field here is a real server knob whose
// `choices` come back from GET /settings/general, so KnobForm renders each as a <Select> — the
// enumerable-values-are-dropdowns rule, satisfied by the same machinery as every other knob.
//
// Deliberately NOT a client-side mapping table. The derivation lives in `config/_profiles.py`
// and reaches this page as `derived_from` on each knob; duplicating it here is how the two would
// drift, and the drift would be invisible because both halves would still render.
const GROUPS: KnobGroup[] = [
  {
    title: "Intent",
    fields: [
      {
        field: "autonomy_profile",
        label: "Autonomy",
        widget: "select",
        help: "How much ground a run covers on its own: the resilience sweep, gap-closing, and the plan/fix iteration budget. Unset = today's individual settings, unchanged.",
      },
      {
        field: "recovery_profile",
        label: "Recovery effort",
        widget: "select",
        help: "How hard a run pushes when it is STUCK — reasoning attempts, model escalation, retry budget. Separate from autonomy because “how far it ranges” and “how hard it pushes on a wall” are different decisions.",
      },
      {
        field: "quality_profile",
        label: "Quality bar",
        widget: "select",
        help: "The code-quality threshold and how many revision passes are spent reaching it.",
      },
      {
        field: "verification_profile",
        label: "Independent verification",
        widget: "select",
        help: "Which independent checks run. Governs GUIDED and ad-hoc runs: on an autonomous run the oracle stack is forced on regardless, which the knobs below report as “forced when autonomous”.",
      },
    ],
  },
];

/** The knobs each selected profile currently supplies, read from the server's `derived_from`
 *  provenance rather than a table kept here. Answers "what did choosing this actually change?"
 *  — and, just as importantly, which of those the operator has since overridden by hand. */
function DerivedSummary() {
  const { data } = useQuery({
    // Same key as KnobForm: react-query serves both from one cached fetch.
    queryKey: ["general-settings"],
    queryFn: () => api.getGeneralSettings(),
  });
  const knobs: Record<string, KnobView> = data?.knobs ?? {};

  const byProfile = new Map<string, { field: string; view: KnobView }[]>();
  for (const [field, view] of Object.entries(knobs)) {
    const owner = view.derived_from;
    if (!owner) continue;
    const rows = byProfile.get(owner) ?? [];
    rows.push({ field, view });
    byProfile.set(owner, rows);
  }

  if (byProfile.size === 0) {
    return (
      <SettingsSection
        title="What your profiles set"
        description={
          <p className="text-sm leading-relaxed text-muted-foreground">
            No profile is selected, so every knob below keeps the value it already had. Choosing a
            profile changes only the knobs you have not set yourself — nothing you configured by
            hand is overwritten.
          </p>
        }
      >
        <span className="sr-only">no profiles selected</span>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection
      title="What your profiles set"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          The knobs each profile supplies. A row marked <em>overridden</em> has an explicit value
          that wins — an explicit setting always outranks a profile.
        </p>
      }
    >
      <div className="flex flex-col items-stretch gap-8">
        {[...byProfile.entries()].map(([owner, rows]) => (
          <section key={owner} className="flex flex-col items-stretch">
            <h3 className="mb-1 text-sm font-semibold text-foreground">
              {profileName(owner)}
              <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">
                {String(knobs[owner]?.value ?? "—")}
              </span>
            </h3>
            <ul className="flex flex-col items-stretch divide-y divide-border/50">
              {rows.map(({ field, view }) => (
                <li
                  key={field}
                  className="flex items-center justify-between gap-6 py-2 text-[13px]"
                >
                  <span className="font-mono text-muted-foreground">{field}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="font-mono text-foreground">{render(view.value)}</span>
                    {view.source !== "profile" && (
                      <span className="font-mono text-[9px] uppercase text-muted-foreground/70">
                        overridden
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </SettingsSection>
  );
}

function render(v: KnobValue): string {
  if (v === true) return "on";
  if (v === false) return "off";
  return v === null || v === undefined ? "—" : String(v);
}

export function BehaviorSettings() {
  return (
    <div className="flex flex-col items-stretch gap-12">
      <KnobForm
        title="Behavior"
        description="State the intent; Mosaera derives the mechanics. These sit BELOW anything you set yourself — a profile only fills a knob you have not configured, so it can never override or weaken an explicit setting. No profile changes what the delivery gate requires."
        groups={GROUPS}
      />
      <DerivedSummary />
    </div>
  );
}
