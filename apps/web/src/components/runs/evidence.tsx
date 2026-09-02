import { useQuery } from "@tanstack/react-query";

import { cn } from "@/lib/utils";

import { api, type RunDetail } from "../../api/client";
import { decisionOf, parseValidationPlan, validationVerdict, type VerdictKind } from "../../lib/runs";
import { DiffView } from "../DiffView";
import { ConsoleLabel, EmptyNote } from "../overview/bits";
import { AmberCallout } from "../ui/AmberCallout";
import { PmMarkdown } from "../pm/PmMarkdown";
import { TONE_BADGE } from "../StatusBadge";

// Shared run status/mode vocabulary — used by both the live workbench and the
// durable history view.
export const STATUS_TONE: Record<string, string> = {
  running: TONE_BADGE.success,
  awaiting_approval: TONE_BADGE.amber,
  cancelling: TONE_BADGE.amber,
  completed: TONE_BADGE.success,
  // Honest non-delivery (iteration cap / no progress / reviewer unsatisfied) — a
  // warning tone: not a success (green), not a crash (red).
  incomplete: TONE_BADGE.amber,
  cancelled: TONE_BADGE.neutral,
  error: TONE_BADGE.destructive,
};

export const STATUS_LABEL: Record<string, string> = {
  running: "Running",
  awaiting_approval: "Awaiting approval",
  cancelling: "Cancelling",
  completed: "Completed",
  incomplete: "Incomplete",
  cancelled: "Cancelled",
  error: "Error",
};

export const MODE_LABEL: Record<string, string> = {
  guided: "Guided",
  autonomous: "Autonomous",
  high_assurance: "High assurance",
};

export const VERDICT_CLS: Record<VerdictKind, string> = {
  pass: "text-success",
  failed: "text-destructive",
  "no-tests": "text-muted-foreground",
  unavailable: "text-muted-foreground",
  unverified: "text-muted-foreground",
  "no-evidence": "text-muted-foreground",
  pending: "text-muted-foreground",
};

/** An honest capability-limit callout: the no-progress breaker stopped the run
 *  because it wasn't converging (rather than looping to the cap / asking for more
 *  budget). Present only when a `capability_limit` decision was persisted. */
export function CapabilityLimitNote({ detail }: { detail: RunDetail | undefined }) {
  const reason = decisionOf(detail, "capability_limit");
  if (!reason) return null;
  return (
    <AmberCallout title="Couldn't complete this task" className="rounded-lg p-4">
      {reason}
    </AmberCallout>
  );
}

/** A question the engine WANTED to ask you, and the rule that stopped it.
 *
 *  The ESCALATE arm raises a clarification when the producer hits a bar it cannot meet. Several
 *  exclusions can withhold that ask — a tamper verdict, a critic veto, a real gate objection. Until
 *  2026-08-21 the withholding was recorded only as an audit row rendered as a muted lifecycle line,
 *  so the operator never learned a question existed. The North Star's `Unsuppressible Ask` requires
 *  suppression to be recorded AND visible; this is the visible half. */
export function WithheldAskNote({ detail }: { detail: RunDetail | undefined }) {
  const reason = decisionOf(detail, "ask_withheld");
  if (!reason) return null;
  return (
    <AmberCallout title="A question was withheld" className="rounded-lg p-4">
      {reason}
    </AmberCallout>
  );
}

export function ValidationEvidence({ detail, live }: { detail: RunDetail | undefined; live: string }) {
  if (!detail) {
    return live ? <Pre text={live} empty="" /> : <EmptyNote>Validation runs during the run.</EmptyNote>;
  }
  const verdict = validationVerdict(detail, detail);
  const plan = parseValidationPlan(detail);
  const output = (detail.test_results ?? []).map((r) => r.output).join("\n\n");
  return (
    <div className="flex flex-col gap-2">
      <p className={cn("text-sm font-medium", VERDICT_CLS[verdict.kind])}>{verdict.label}</p>
      {verdict.helper && <p className="text-xs text-muted-foreground">{verdict.helper}</p>}
      {plan && (plan.results ?? []).length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {(plan.results ?? []).map((s, i) => (
            <li key={i} className="flex items-center gap-2 font-mono text-[11px]">
              <span className={cn("size-1.5 rounded-full", s.ok ? "bg-success" : "bg-destructive")} aria-hidden />
              <span className="text-foreground/80">{s.name}</span>
              <span className="text-muted-foreground/60">
                {s.timed_out ? "TIMED OUT" : `exit code ${s.exit_code}`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {output && <Pre text={output} empty="" />}
    </div>
  );
}

/** The per-run delivery report, fetched from the real endpoint. A missing
 *  report is exactly a 404 — never synthesized. (Relocated from the Artifacts
 *  tab — a delivery report is run evidence, not a project document.) */
export function RunReportSection({ rid }: { rid: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["run-report", rid],
    queryFn: () => api.runReport(rid),
    retry: false, // a 404 is an honest answer, not a flake
  });
  if (isLoading) return null;
  return (
    <div className="flex flex-col gap-1">
      <ConsoleLabel>Run report</ConsoleLabel>
      {error ? (
        <p className="text-sm text-muted-foreground">
          {String(error).includes("404") ? "No report was recorded for this run." : String(error)}
        </p>
      ) : data ? (
        <div className="max-h-96 overflow-y-auto rounded-md bg-background/50 px-3 py-2 text-sm leading-relaxed [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
          <PmMarkdown>{data.markdown}</PmMarkdown>
        </div>
      ) : null}
    </div>
  );
}

/** Rendered-markdown for decisions (plan / review / summary) — the readable win
 *  over the old raw pre-wrap dump. Untrusted content is safe (react-markdown
 *  escapes raw HTML). */
export function Prose({ text, empty }: { text: string; empty: string }) {
  if (!text.trim()) return empty ? <EmptyNote>{empty}</EmptyNote> : null;
  return (
    <div className="max-h-[28rem] overflow-auto rounded-md bg-background/50 px-3 py-2 text-sm text-foreground/90 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
      <PmMarkdown>{text}</PmMarkdown>
    </div>
  );
}

/** Raw monospace output (test logs, gate text) — NOT markdown. */
export function Pre({ text, empty }: { text: string; empty: string }) {
  if (!text) return empty ? <EmptyNote>{empty}</EmptyNote> : null;
  return (
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-background p-2 font-mono text-[11px] leading-relaxed text-foreground/80 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
      {text}
    </pre>
  );
}

export function DiffOrEmpty({ diff }: { diff: string }) {
  if (!diff.trim()) return <EmptyNote>No diff recorded.</EmptyNote>;
  return <DiffView diff={diff} />;
}
