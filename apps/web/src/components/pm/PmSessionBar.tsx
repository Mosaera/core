import { Archive, MessageSquarePlus } from "lucide-react";

import type { PmSession } from "@/api/sessions";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Session switcher for the PM tab: pick a thread, start a new one, or archive the current
 *  one. Purely presentational — the workspace owns the create/switch/archive mutations. */
export function PmSessionBar({
  sessions,
  selectedId,
  onSelect,
  onNew,
  onArchive,
  busy = false,
}: {
  sessions: PmSession[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onArchive: (id: string) => void;
  busy?: boolean;
}) {
  const label = (s: PmSession) => s.title.trim() || "New session";
  const hasSessions = sessions.length > 0;

  return (
    /* The rule stays full-bleed; its CONTENTS line up with the transcript and
       composer below, which both centre at max-w-4xl. */
    <div className="border-b border-border/60 px-4 py-2">
      <div className="mx-auto flex w-full max-w-4xl items-center gap-2">
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        Session
      </span>
      {hasSessions ? (
        <Select
          value={selectedId ?? undefined}
          onValueChange={(v) => {
            if (v) onSelect(v);
          }}
        >
          <SelectTrigger
            aria-label="Select session"
            className="h-8 min-w-0 max-w-[280px] flex-1 text-sm"
          >
            <SelectValue placeholder="Select a session" />
          </SelectTrigger>
          <SelectContent>
            {sessions.map((s) => (
              <SelectItem key={s.id} value={s.id} className="text-sm">
                <span className="truncate">{label(s)}</span>
                <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                  {s.message_count}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <span className="flex-1 text-sm text-muted-foreground">No sessions yet</span>
      )}
      <Button
        size="sm"
        variant="outline"
        className="h-8 gap-1.5"
        onClick={onNew}
        disabled={busy}
      >
        <MessageSquarePlus className="size-3.5" />
        New
      </Button>
      {selectedId && (
        <Button
          size="sm"
          variant="ghost"
          aria-label="Archive session"
          title="Archive this session"
          className="h-8 gap-1.5 text-muted-foreground hover:text-foreground"
          onClick={() => onArchive(selectedId)}
          disabled={busy}
        >
          <Archive className="size-3.5" />
        </Button>
      )}
      </div>
    </div>
  );
}
