import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import { api } from "../../api/client";
import { SettingsSection } from "./SettingsSection";

/** Settings (admin): give the delivery agent a human-gated `delete_file` tool. OFF by
 *  default — deletion is destructive, so it is an explicit opt-in. When off, deletion
 *  stays out of capability and is surfaced to the stakeholder as manual steps. The
 *  save goes through adminFetch, so a non-admin gets a 403 and AdminUnlock re-prompts. */
export function DeleteToolCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["features"], queryFn: () => api.features() });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const enabled = Boolean(data?.delete_tool_enabled);

  async function toggle() {
    setBusy(true);
    setErr(null);
    try {
      qc.setQueryData(["features"], await api.setDeleteTool(!enabled));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsSection
      title="File deletion (admin)"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          Allow the delivery agent to <span className="text-foreground">delete files</span> via a
          human-approved <code className="text-foreground">delete_file</code> tool.{" "}
          <span className="text-foreground">Destructive — off by default.</span> While off, deletion
          stays out of capability and is surfaced to you as manual steps.
        </p>
      }
    >
      <div className="flex items-center gap-3">
        <Button
          size="sm"
          variant={enabled ? "destructive" : "default"}
          onClick={() => void toggle()}
          disabled={busy}
        >
          {busy ? "Saving…" : enabled ? "Disable deletion" : "Enable deletion"}
        </Button>
        <span className="font-mono text-[11px] text-muted-foreground">
          {enabled ? "enabled" : "disabled"}
        </span>
      </div>
      {err && <p className="font-mono text-[11px] text-destructive">{err}</p>}
    </SettingsSection>
  );
}
