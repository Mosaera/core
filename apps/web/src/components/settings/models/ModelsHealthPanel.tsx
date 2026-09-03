import { useQuery } from "@tanstack/react-query";

import { firstRunApi } from "../../../api/firstRun";
import { backendChecks, environmentChecks } from "../../../lib/firstRun";
import { CheckRowView } from "../../setup/CheckRow";
import { SettingsSection } from "../SettingsSection";

/** GET /api/preflight's per-check rows, surfaced where an operator already is instead of
 *  only on first run (#119 task 6). SetupBanner stays the top-level pointer ("something
 *  needs attention, go here"); this is the "here" — each check's own status, explanation,
 *  and copyable fix, reusing `CheckRowView` (the first-run wizard's row, unimported since
 *  ADR-0116 moved the wizard to the terminal — revived rather than duplicated).
 *
 *  `embed_model` needs no special casing: it is already folded into the Ollama backend
 *  check's required-model set (`preflight.required_ollama_models`), so a missing embedding
 *  model surfaces here with its own `ollama pull` fix exactly like a missing chat model. */
export function ModelsHealthPanel() {
  const { data, isError } = useQuery({
    queryKey: ["preflight"],
    queryFn: () => firstRunApi.preflight(true),
    refetchInterval: 60_000,
  });

  if (isError) {
    return (
      <SettingsSection title="Health">
        <p className="text-sm text-destructive">
          Couldn't check this instance's readiness — the check itself failed.
        </p>
      </SettingsSection>
    );
  }
  if (!data) return null;

  const backend = backendChecks(data);
  const environment = environmentChecks(data);
  if (backend.length === 0 && environment.length === 0) return null;

  return (
    <SettingsSection
      title="Health"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          What this instance can actually reach right now — the same checks{" "}
          <code className="font-mono text-[12px]">mosaera doctor</code> prints. Nothing here
          writes config; a fix is always a command you run yourself.
        </p>
      }
    >
      <div className="flex flex-col gap-4">
        {[...backend, ...environment].map((c) => (
          <CheckRowView key={c.key} check={c} />
        ))}
      </div>
    </SettingsSection>
  );
}
