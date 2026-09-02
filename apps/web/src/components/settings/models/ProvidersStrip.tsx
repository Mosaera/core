import { type ProvidersState } from "../../../api/client";
import { SettingsSection } from "../SettingsSection";
import { ProviderCard } from "./ProviderCard";

/** The connections strip: the always-on local Ollama card plus a card per hosted
 *  provider. Ordered local-first so the free default reads as the baseline. Keys
 *  are stored server-side and never shown back. */
export function ProvidersStrip({ providers }: { providers: ProvidersState }) {
  const ordered = [...providers.providers].sort((a, b) => Number(b.local) - Number(a.local));

  return (
    <SettingsSection
      title="Providers"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          Where models come from. Ollama runs locally and is always available; add an API key to
          route a role to a hosted model. Keys are stored server-side (0600) and never shown back.
        </p>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {ordered.map((p) => (
          <ProviderCard key={p.id} provider={p} />
        ))}
      </div>
    </SettingsSection>
  );
}
