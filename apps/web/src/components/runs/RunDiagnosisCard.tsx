import { Badge } from "@/components/ui/badge";

import type { RunDiagnosis } from "../../api/client";
import { gateReason, OUTCOME_PLAIN, parkCause, STOP_CHANNELS } from "../../lib/plain";
import { gateRemedy } from "../../lib/remedy";
import { ConsoleLabel } from "../overview/bits";

/* How a run ENDED, structured (#75).

   Until this existed a finished run showed `termination_reason` — one 80-character line — so a
   failure seen here could not be compared against the same failure last week. The benchmark had
   the outcome bucket, the park cause, the gate reasons and the vouch all along, which is why the
   benchmark kept finding defects this screen never surfaced.

   Read-only and derived from nothing: every field is rendered exactly as the API recorded it. A
   missing field renders as absent, never as a guess — the whole point is that a reader can trust
   what is on the screen three days later. */

const OUTCOME_TONE: Record<string, string> = {
  clean_deliver: "text-emerald-600 dark:text-emerald-400",
  honest_park: "text-amber-600 dark:text-amber-400",
  thrash_park: "text-orange-600 dark:text-orange-400",
  false_ship: "text-red-600 dark:text-red-400",
  crash: "text-red-600 dark:text-red-400",
};

export function RunDiagnosisCard({ diagnosis }: { diagnosis: RunDiagnosis }) {
  const outcome = diagnosis.outcome ?? "";
  const stops = STOP_CHANNELS.filter((c) => diagnosis[c.key]);
  const reasons = diagnosis.gate_reasons ?? [];
  const claims = diagnosis.unsatisfied_claims ?? [];
  const cap = diagnosis.max_iterations;
  // One line per reason that has a remedy on file; a reason without one renders nothing rather
  // than a guess. Deduped by sentence: three reasons that all resolve to "re-run" say it once.
  const seen = new Set<string>();
  const remedies = reasons
    .map((reason) => ({ reason, remedy: gateRemedy(reason, diagnosis.oracle_blocked_by ?? []) }))
    .filter((r): r is { reason: string; remedy: { text: string; knob?: string } } => {
      if (!r.remedy || seen.has(r.remedy.text)) return false;
      seen.add(r.remedy.text);
      return true;
    });

  return (
    <section className="flex flex-col gap-1.5">
      <ConsoleLabel>How it ended</ConsoleLabel>
      <div className="flex flex-col gap-2 rounded-lg bg-card p-3 ring-1 ring-white/12">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className={`text-sm font-medium ${OUTCOME_TONE[outcome] ?? "text-foreground"}`}>
            {OUTCOME_PLAIN[outcome] ?? outcome ?? "—"}
          </span>
          <span className="font-mono text-[10px] text-muted-foreground/70">{outcome}</span>
          {diagnosis.park_cause && (
            <Badge variant="outline" className="font-mono text-[10px]">
              {diagnosis.park_cause}
            </Badge>
          )}
        </div>

        {/* The park cause in plain words — the raw token stays above (this card's
            charter is the exact record; the sentence is a reading, labeled as such). */}
        {diagnosis.park_cause && (
          <p className="text-[11px] leading-snug text-foreground/80">
            {parkCause(diagnosis.park_cause)}
          </p>
        )}

        {stops.map(({ key, label }) => (
          <p key={key} className="text-[11px] leading-snug text-foreground/80">
            <span className="text-muted-foreground">{label} — </span>
            {String(diagnosis[key])}
          </p>
        ))}

        {reasons.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Blocked at the gate by
            </span>
            <div className="flex flex-wrap gap-1">
              {reasons.map((r) => (
                <Badge key={r} variant="outline" className="text-[10px]">
                  {gateReason(r)}
                </Badge>
              ))}
            </div>
            {/* What to DO about it (#121). #108 made the cause visible and left the reader with
                no next step, which for someone who has not read the docs is the same dead end.
                Specialised by which oracle leg refused — the run has always recorded it. */}
            {remedies.length > 0 && (
              <ul className="mt-0.5 flex flex-col gap-1">
                {remedies.map(({ reason, remedy }) => (
                  <li key={reason} className="text-[11px] leading-snug text-foreground/80">
                    {remedy.text}
                    {remedy.knob && (
                      <span className="ml-1 font-mono text-[10px] text-muted-foreground">
                        ({remedy.knob})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {claims.length > 0 && (
          <p className="font-mono text-[10px] text-muted-foreground">
            unverified claims: {claims.join(", ")}
          </p>
        )}

        <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-muted-foreground/80">
          {typeof diagnosis.iteration === "number" && (
            <span>
              iteration {diagnosis.iteration}
              {typeof cap === "number" ? `/${cap}` : ""}
            </span>
          )}
          {/* The vouch diagnosis (#60): why the oracle vouched, or which guard said no. It exists
              because a control whose non-firing is invisible costs a day of archaeology. */}
          {diagnosis.vouch && <span>{diagnosis.vouch}</span>}
          {diagnosis.tests_modified && <span className="text-red-500">tests modified</span>}
          {diagnosis.coder_escalated && <span>coder raised a hand</span>}
        </div>
      </div>
    </section>
  );
}
