import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

import { api, type RoleBinding } from "../../../api/client";
import { overridesOf } from "../../../lib/models";
import { PresetSwitcher } from "./PresetSwitcher";
import { PricingDisclosure } from "./PricingDisclosure";
import { ProvidersStrip } from "./ProvidersStrip";
import { RolesTable } from "./RolesTable";

/** Settings › Models — the calm redesign. Answers "which brain runs which job, at
 *  what cost, can I trust it there?" top-to-bottom: a preset switcher (the anchor),
 *  the roles table (the heart), the providers strip (connections), and pricing
 *  (tucked away). Presets ARE the cost modes; the table edits the active preset's
 *  effective bindings. All chips are truthful — no synthesized capability data. */
export function ModelsSettings() {
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data: providers } = useQuery({ queryKey: ["providers"], queryFn: () => api.getProviders() });
  const { data: costModes } = useQuery({ queryKey: ["cost-modes"], queryFn: () => api.getCostModes() });
  const { data: pricing } = useQuery({ queryKey: ["pricing"], queryFn: () => api.getPricing() });

  // The preset being viewed/edited — seeded from (and kept in step with) the
  // server's default-for-new-runs. Selecting a preset makes it the default.
  const [activePreset, setActivePreset] = useState<string | null>(null);
  useEffect(() => {
    if (costModes && activePreset === null) setActivePreset(costModes.default_cost_mode);
  }, [costModes, activePreset]);

  // Persist the full cost-mode map (all overrides) plus the default — the shape
  // saveCostModes replaces wholesale. Optimistic-quiet: the poll stays authoritative.
  async function persistCostModes(
    overrides: Record<string, Record<string, RoleBinding>>,
    defaultMode: string,
  ) {
    try {
      await api.saveCostModes({ modes: overrides, default_cost_mode: defaultMode });
      await qc.invalidateQueries({ queryKey: ["cost-modes"] });
      await qc.invalidateQueries({ queryKey: ["models"] });
      toast({ title: "Saved", variant: "success" });
    } catch (e) {
      toast({ title: "Couldn't save", description: msgOf(e), variant: "error" });
    }
  }

  // The base role bindings — the fallback every preset inherits when it doesn't
  // override a role. Edited in the demoted "Role defaults" disclosure.
  async function persistBaseRoles(roles: Record<string, RoleBinding>) {
    try {
      await api.saveProviders({ roles });
      await qc.invalidateQueries({ queryKey: ["providers"] });
      await qc.invalidateQueries({ queryKey: ["cost-modes"] });
      toast({ title: "Saved", variant: "success" });
    } catch (e) {
      toast({ title: "Couldn't save", description: msgOf(e), variant: "error" });
    }
  }

  function selectPreset(mode: string) {
    setActivePreset(mode);
    if (costModes) void persistCostModes(overridesOf(costModes), mode);
  }

  if (!providers || !costModes || !pricing) {
    return <Skeleton className="h-96 w-full" />;
  }

  const preset = activePreset ?? costModes.default_cost_mode;
  const localIds = new Set(providers.providers.filter((p) => p.local).map((p) => p.id));
  const hasHostedKey = providers.providers.some((p) => !p.local && p.configured);

  return (
    <div className="flex flex-col gap-12">
      <PresetSwitcher
        costModes={costModes}
        activePreset={preset}
        localProviderIds={localIds}
        onSelect={selectPreset}
      />

      {/* Providers first: you connect a provider before you can route a role to
          one of its models. */}
      <ProvidersStrip providers={providers} />

      <RolesTable
        costModes={costModes}
        activePreset={preset}
        providers={providers}
        pricing={pricing}
        localProviderIds={localIds}
        onSaveOverrides={persistCostModes}
        onSaveBaseRoles={persistBaseRoles}
      />

      {hasHostedKey && (
        <PricingDisclosure pricing={pricing} sources={providers.sources} />
      )}
    </div>
  );
}

function msgOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
