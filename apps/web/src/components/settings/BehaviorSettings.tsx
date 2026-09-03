import { useQuery } from "@tanstack/react-query";

import { api, type KnobValue, type KnobView, type ProfileEffect } from "../../api/client";
import { KnobForm, type KnobGroup, profileName } from "./KnobForm";
import { SettingsSection } from "./SettingsSection";

// The intent surface (ADR-0122): the operator states how hard to try, how high the bar is and how
// much independent checking to demand; the SERVER derives the individual knobs.
//
// THREE profiles, not four. `autonomy` and `recovery` both answered "how hard does it try?" and
// were indistinguishable in use, so they are one.
const GROUPS: KnobGroup[] = [
  {
    title: "Intent",
    fields: [
      {
        field: "effort_profile",
        label: "Effort",
        widget: "select",
        help: "How hard a run tries before it stops and asks you: how many recovery attempts it gets, whether it may escalate to a stronger model, how long it persists. Unset = your current individual settings, unchanged.",
      },
      {
        field: "quality_profile",
        label: "Quality bar",
        widget: "select",
        help: "The code-quality threshold a change must reach, and how many revision passes are spent reaching it.",
      },
      {
        field: "verification_profile",
        label: "Independent verification",
        widget: "select",
        help: "Which independent checks must run. Governs guided and ad-hoc runs: on an autonomous run the oracle stack is forced on regardless.",
      },
    ],
  },
];

function render(v: KnobValue): string {
  if (v === true) return "on";
  if (v === false) return "off";
  return v === null || v === undefined ? "—" : String(v);
}

/** Every option for one profile, side by side.
 *
 *  A three-way dial labelled only "cautious / balanced / persistent" asks the reader to decode an
 *  adjective. Showing the options against each other — in sentences, not knob identifiers — is
 *  what lets someone predict the difference before committing to it. The rows come from the API,
 *  so this cannot drift from the derivation tables the engine actually uses.
 */
function ProfileComparison({
  field,
  options,
  selected,
  knobs,
}: {
  field: string;
  options: Record<string, ProfileEffect[]>;
  selected: KnobValue;
  knobs: Record<string, KnobView>;
}) {
  const choices = Object.keys(options);
  // Only rows that actually DIFFER across the options: a line identical in all three is noise
  // that hides the decision the reader came to make.
  const varying = [...new Set(choices.flatMap((c) => options[c].map((e) => e.field)))].filter(
    (f) => new Set(choices.map((c) => JSON.stringify(valueIn(options[c], f)))).size > 1,
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[38rem] border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-border/60">
            <th className="py-2 pr-4 text-left font-medium text-muted-foreground">
              {profileName(field)} changes
            </th>
            {choices.map((c) => (
              <th
                key={c}
                className={
                  c === selected
                    ? "px-3 py-2 text-left font-semibold text-primary"
                    : "px-3 py-2 text-left font-medium text-muted-foreground"
                }
              >
                {c}
                {c === selected && <span className="ml-1 text-[10px] uppercase">selected</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {varying.map((f) => (
            <tr key={f} className="border-b border-border/30 last:border-0">
              <td className="py-2 pr-4 text-muted-foreground">
                {effectIn(options, f) || f}
                {/* The profile owns this knob but an explicit setting outranks it. Without this
                    the row promises something the deployment is not doing. */}
                {knobs[f]?.derived_from === field && knobs[f]?.source !== "profile" && (
                  <span className="ml-2 font-mono text-[9px] uppercase text-muted-foreground/70">
                    you set this to {render(knobs[f]?.value ?? null)}
                  </span>
                )}
              </td>
              {choices.map((c) => (
                <td
                  key={c}
                  className={
                    c === selected
                      ? "px-3 py-2 font-mono font-medium text-foreground"
                      : "px-3 py-2 font-mono text-muted-foreground"
                  }
                >
                  {render(valueIn(options[c], f))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function valueIn(effects: ProfileEffect[] | undefined, field: string): KnobValue {
  return effects?.find((e) => e.field === field)?.value ?? null;
}
function effectIn(options: Record<string, ProfileEffect[]>, field: string): string {
  for (const effects of Object.values(options)) {
    const hit = effects.find((e) => e.field === field);
    if (hit?.effect) return hit.effect;
  }
  return "";
}

function ProfileReference() {
  const { data } = useQuery({
    // Same key as KnobForm: react-query serves both from one cached fetch.
    queryKey: ["general-settings"],
    queryFn: () => api.getGeneralSettings(),
  });
  const knobs: Record<string, KnobView> = data?.knobs ?? {};
  const profiles = data?.profiles ?? {};
  const constant = data?.constant ?? [];

  return (
    <div className="flex flex-col items-stretch gap-12">
      {Object.entries(profiles).map(([field, options]) => (
        <SettingsSection
          key={field}
          title={`${profileName(field)} — what each option does`}
          description={
            <p className="text-sm leading-relaxed text-muted-foreground">
              Only the settings that differ between the options are listed. These describe what a
              run will <em>do</em>; they are not a claim about how often it succeeds — that has not
              been measured.
            </p>
          }
        >
          <ProfileComparison
            field={field}
            options={options}
            selected={knobs[field]?.value ?? null}
            knobs={knobs}
          />
        </SettingsSection>
      ))}

      {constant.length > 0 && (
        <SettingsSection
          title="What no profile changes"
          description={
            <p className="text-sm leading-relaxed text-muted-foreground">
              Effort changes how hard a run tries, never what evidence it must produce. These are
              identical whichever option you pick, and a test enforces it.
            </p>
          }
        >
          <ul className="flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-muted-foreground">
            {constant.map((f) => (
              <li key={f} className="font-mono">
                {f}
              </li>
            ))}
          </ul>
        </SettingsSection>
      )}
    </div>
  );
}

export function BehaviorSettings() {
  return (
    <div className="flex flex-col items-stretch gap-12">
      <KnobForm
        title="Behavior"
        description="State the intent; Mosaera derives the mechanics. These sit BELOW anything you set yourself — a profile only fills a knob you have not configured, so it can never override or weaken an explicit setting."
        groups={GROUPS}
      />
      <ProfileReference />
    </div>
  );
}
