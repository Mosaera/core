import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { keysApi, type ApiKeyRow } from "../../api/keys";
import { EmptyNote } from "../overview/bits";
import { TONE_BADGE } from "../StatusBadge";
import { SettingsSection } from "./SettingsSection";

/** Settings: per-user API keys (ADR-0127) — a revocable, attributed credential for headless
 *  callers, replacing "share the one MOSAERA_API_TOKEN with everyone".
 *
 *  Two things this surface must get right, both about what a key is NOT:
 *  - it is never admin, even yours, so the copy says so where the key is issued rather than
 *    leaving someone to assume their own key inherits their privileges;
 *  - the plaintext exists exactly once. The reveal is deliberately interruptive, because a
 *    dismissed-too-early key is unrecoverable and the only remedy is issuing another. */
export function ApiKeysCard() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["api-keys"], queryFn: () => keysApi.list() });
  const [name, setName] = useState("");
  const [issued, setIssued] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const create = useMutation({
    mutationFn: () => keysApi.create(name.trim()),
    onSuccess: (row) => {
      setIssued(row.key);
      setName("");
      setErr(null);
      setCopied(false);
      void qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
  });

  const revoke = useMutation({
    mutationFn: (id: number) => keysApi.revoke(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["api-keys"] }),
    onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
  });

  const keys = data?.keys ?? [];
  const live = keys.filter((k) => !k.revoked);

  return (
    <SettingsSection
      title="API keys"
      description={
        <p className="text-sm leading-relaxed text-muted-foreground">
          Credentials for headless callers — CI, a script, the CLI. Each one is{" "}
          <span className="text-foreground">revocable on its own</span>, so retiring a key does not
          disturb anything else.{" "}
          <span className="text-foreground">
            A key is never an admin credential, even when you are an admin
          </span>{" "}
          — it reads and submits runs; it cannot change configuration, write secrets, manage
          accounts, or issue another key.
        </p>
      }
    >
      {issued && (
        <div className="flex flex-col gap-3 border border-amber-500/40 bg-amber-500/5 p-4">
          <div className="flex items-center gap-2">
            <Badge className={cn("font-mono text-[10px] uppercase", TONE_BADGE.amber)}>
              copy it now
            </Badge>
            <span className="text-sm font-semibold text-foreground">
              This is the only time you will see this key
            </span>
          </div>
          <code className="block break-all bg-background/60 p-3 font-mono text-xs text-foreground">
            {issued}
          </code>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => {
                void navigator.clipboard?.writeText(issued).then(() => setCopied(true));
              }}
            >
              {copied ? "Copied" : "Copy"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setIssued(null)}>
              Done
            </Button>
            <span className="text-xs text-muted-foreground">
              It is stored hashed — we cannot show it again, only issue a new one.
            </span>
          </div>
        </div>
      )}

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create.mutate();
        }}
      >
        <Input
          aria-label="Key name"
          className="max-w-xs"
          placeholder="What is it for? e.g. ci, laptop"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={64}
        />
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          {create.isPending ? "Creating…" : "Create key"}
        </Button>
      </form>

      {err && <p className="text-sm text-destructive">{err}</p>}

      {isLoading ? (
        <EmptyNote>Loading…</EmptyNote>
      ) : keys.length === 0 ? (
        <EmptyNote>No keys yet. Create one to call the API without a browser session.</EmptyNote>
      ) : (
        <div className="flex flex-col">
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 border-b border-border/60 pb-2 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
            <span>Name</span>
            <span>Created</span>
            <span>Last used</span>
            <span className="sr-only">Actions</span>
          </div>
          {keys.map((k) => (
            <KeyRow key={k.id} row={k} onRevoke={() => revoke.mutate(k.id)} />
          ))}
        </div>
      )}

      {live.length >= 20 && (
        <p className="text-sm text-muted-foreground">
          You have {live.length} live keys — the maximum. Revoke one before creating another.
        </p>
      )}
    </SettingsSection>
  );
}

function KeyRow({ row, onRevoke }: { row: ApiKeyRow; onRevoke: () => void }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <div
      className={cn(
        "grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-4 border-b border-border/40 py-2 text-sm",
        row.revoked && "opacity-50",
      )}
    >
      <span className="min-w-0 truncate text-foreground">{row.name || "(unnamed)"}</span>
      <span className="font-mono text-xs text-muted-foreground">{shortDate(row.created_at)}</span>
      <span className="font-mono text-xs text-muted-foreground">
        {/* "Never" is the operator's signal that revoking is safe — an unused key is one nothing
            depends on. Blank would read as missing data rather than as an answer. */}
        {row.last_used_at ? shortDate(row.last_used_at) : "never"}
      </span>
      {row.revoked ? (
        <Badge className={cn("font-mono text-[10px] uppercase", TONE_BADGE.neutral)}>revoked</Badge>
      ) : confirming ? (
        <span className="flex items-center gap-1">
          <Button size="sm" variant="destructive" onClick={onRevoke}>
            Revoke
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            Cancel
          </Button>
        </span>
      ) : (
        <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
          Revoke
        </Button>
      )}
    </div>
  );
}

function shortDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}
