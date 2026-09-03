import { Download, ExternalLink } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";

import { CopyButton } from "@/components/ui/CopyButton";

import { api, type RunCost, type RunDetail } from "../../api/client";
import { parseDiff } from "../../lib/diff";
import type { LedgerRow } from "../../lib/ledger";
import { parseQuality } from "../../lib/runs";
import { ChecksumVerify } from "./ChecksumVerify";

type SealRow = Extract<LedgerRow, { kind: "seal" }>;

function Fact({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <span title={title}>
      <span className="text-muted-foreground/60">{label}</span>{" "}
      <span className="text-muted-foreground">{value}</span>
    </span>
  );
}

/** The quiet RECORD footer: everything auditable, nothing shouting — the
 *  integrity checksum (with in-browser verification), a small facts grid, and
 *  the technical links. Facts render even on a live run; the checksum only once
 *  a seal exists. Null stamps read "not recorded" — never proxied. */
export function RecordFooter({
  rid,
  seal,
  detail,
  cost,
  budget,
  profiles,
}: {
  rid: string;
  seal: SealRow | null;
  detail?: RunDetail;
  cost?: RunCost | null;
  budget?: Record<string, number> | null;
  /** The intent profiles this run STARTED with (ADR-0122). Shown beside the run's own numbers so
   *  the profile reads as an observation about THIS run rather than a promise about runs in
   *  general — which is all a label can honestly be until the effect is measured. */
  profiles?: Record<string, string> | null;
}) {
  const files = useMemo(
    () => (detail ? parseDiff(detail.repo_changes[0]?.diff ?? "").filter((f) => f.path) : []),
    [detail],
  );
  const totals = files.reduce(
    (a, f) => ({ adds: a.adds + f.adds, dels: a.dels + f.dels }),
    { adds: 0, dels: 0 },
  );
  const quality = useMemo(() => parseQuality(detail), [detail]);
  const spend = cost ?? detail?.cost ?? null;
  // The IMPUTED cost of on-box models, shown only when nothing was actually billed. Without it
  // the receipt reads a flat "$0.00" for a run that would have cost real money on a hosted
  // model — which is the number an operator needs BEFORE switching to one. Marked "shadow" so
  // it can never be mistaken for a bill (same rule as RunDetailPanel).
  const shadowUsd = spend && spend.usd === 0 ? (spend.shadow_usd ?? 0) : 0;
  const finished = seal?.finishedAt
    ? new Date(seal.finishedAt).toLocaleString(undefined, { hour12: false })
    : null;

  return (
    <footer className="mt-2 flex flex-col gap-3 border-t border-border/60 pt-4">
      <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground/50">
        Record
      </span>

      {seal &&
        (seal.receiptId ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-1.5">
              <code className="min-w-0 break-all font-mono text-[12px] text-foreground/70">
                sha256 · {seal.receiptId}
              </code>
              <CopyButton
                text={seal.receiptId}
                label="Copy checksum"
                className="size-5"
                iconClassName="size-3"
              />
            </div>
            <p className="max-w-3xl text-[13px] leading-relaxed text-muted-foreground/80">
              A fingerprint of this record, computed when the run finished from the run id, the
              commit, the engine version, and the receipt. If any of those facts were altered, the
              fingerprint would no longer match.
            </p>
            <ChecksumVerify row={seal} />
          </div>
        ) : (
          <p className="font-mono text-[11px] text-muted-foreground">
            No checksum was recorded for this run.
          </p>
        ))}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 font-mono text-[12px] tabular-nums">
        {Object.entries(profiles ?? {}).map(([field, choice]) => (
          <Fact
            key={field}
            label={field.replace(/_profile$/, "")}
            value={choice}
            title="The profile this run started with — recorded once, so a later settings change cannot re-describe it."
          />
        ))}
        {detail?.commit_sha && <Fact label="commit" value={detail.commit_sha.slice(0, 8)} />}
        {detail?.branch && <Fact label="branch" value={detail.branch} />}
        {detail && detail.iterations > 0 && (
          <Fact
            label="revisions"
            value={String(detail.iterations)}
          />
        )}
        {quality && (
          <Fact
            label="code quality"
            value={`${quality.composite}/100 advisory`}
            title={quality.dimensions.map((d) => `${d.name}: ${d.score ?? "N/A"}`).join(" · ")}
          />
        )}
        {files.length > 0 && (
          <Fact
            label="changed"
            value={`${files.length} file${files.length === 1 ? "" : "s"} +${totals.adds} −${totals.dels}`}
          />
        )}
        {spend && spend.total_tokens > 0 && (
          <Fact
            label="spent"
            value={`${spend.total_tokens.toLocaleString()} tokens${
              budget?.tokens ? ` / ${budget.tokens.toLocaleString()}` : ""
            } · ${spend.usd > 0 ? `$${spend.usd.toFixed(4)}` : "$0.00"}${
              budget?.usd ? ` / $${budget.usd}` : ""
            }${shadowUsd > 0 ? ` · ~$${shadowUsd.toFixed(4)} shadow` : ""}`}
            title={`${spend.calls} model call${spend.calls === 1 ? "" : "s"}${
              shadowUsd > 0 ? " · shadow = imputed cost of on-box models, not billed" : ""
            }`}
          />
        )}
        {finished && <Fact label="finished" value={finished} />}
        <Fact
          label="engine"
          value={seal ? (seal.engineVersion ? `v${seal.engineVersion}` : "version not recorded") : "—"}
        />
      </div>

      <div className="flex flex-wrap items-center gap-4 font-mono text-[12px] text-muted-foreground">
        {detail && (
          <a href={api.patchUrl(rid)} download className="flex items-center gap-1 hover:text-foreground">
            <Download className="size-3" />
            download patch
          </a>
        )}
        {detail?.project_id && (
          <Link
            to={`/projects/${detail.project_id}/delivery?view=changes`}
            className="flex items-center gap-1 hover:text-foreground"
          >
            <ExternalLink className="size-3" />
            merge from the project
          </Link>
        )}
      </div>
    </footer>
  );
}
