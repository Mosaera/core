import {
  type CostModesState,
  type Pricing,
  type ProvidersState,
  type RoleBinding,
} from "../../../api/client";
import { overridesOf, presetLabel } from "../../../lib/models";
import { ConsoleLabel } from "../../overview/bits";
import { SettingsSection } from "../SettingsSection";
import { RoleDefaultsDisclosure } from "./RoleDefaultsDisclosure";
import { RoleRow } from "./RoleRow";

/** The heart of the Models screen: one row per role, showing the active preset's
 *  effective binding. Editing a row writes an override for that preset; a per-row
 *  reset clears it back to the base default. The base defaults themselves live in
 *  a demoted disclosure below. */
export function RolesTable({
  costModes,
  activePreset,
  providers,
  pricing,
  localProviderIds,
  onSaveOverrides,
  onSaveBaseRoles,
}: {
  costModes: CostModesState;
  activePreset: string;
  providers: ProvidersState;
  pricing: Pricing;
  localProviderIds: Set<string>;
  onSaveOverrides: (
    overrides: Record<string, Record<string, RoleBinding>>,
    defaultMode: string,
  ) => void;
  onSaveBaseRoles: (roles: Record<string, RoleBinding>) => void;
}) {
  const overrides = overridesOf(costModes);

  function setOverride(role: string, binding: RoleBinding | null) {
    const modeMap = { ...(overrides[activePreset] ?? {}) };
    if (binding && binding.provider && binding.model) modeMap[role] = binding;
    else delete modeMap[role];
    onSaveOverrides({ ...overrides, [activePreset]: modeMap }, costModes.default_cost_mode);
  }

  return (
    <SettingsSection
      title="Roles"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          The six jobs of the team, each bound to one model under the{" "}
          <b className="text-foreground">{presetLabel(activePreset)}</b> preset. Change a row to
          override just that role; reset to fall back to the default.
        </p>
      }
    >
      <div className="flex flex-col">
        {/* Column header (wide screens only) */}
        <div className="hidden grid-cols-[minmax(11rem,1.3fr)_minmax(0,1.5fr)_minmax(0,1.2fr)] gap-x-4 pb-1 lg:grid">
          <ConsoleLabel>Role</ConsoleLabel>
          <ConsoleLabel>Model</ConsoleLabel>
          <span />
        </div>

        {costModes.role_meta.map((m) => (
          <RoleRow
            key={m.role}
            meta={m}
            cell={costModes.modes[activePreset]?.[m.role]}
            sources={providers.sources}
            pricing={pricing}
            localProviderIds={localProviderIds}
            onChange={(binding) => setOverride(m.role, binding)}
            onReset={() => setOverride(m.role, null)}
          />
        ))}
      </div>

      <RoleDefaultsDisclosure providers={providers} onSave={onSaveBaseRoles} />
    </SettingsSection>
  );
}
