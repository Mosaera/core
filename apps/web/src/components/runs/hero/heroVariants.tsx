import { useEffect, useState } from "react";

import type { HonestyBadge, LedgerRow } from "../../../lib/ledger";
import { TERMINATED } from "../../../lib/plain";
import { ClaimBar } from "./ClaimBar";

function heroClaims(rows: LedgerRow[]) {
  const decomposition = rows.find((r) => r.kind === "decomposition");
  return decomposition?.kind === "decomposition" ? decomposition.claims : [];
}

/** Delivered: the claim bar only. The verdict SENTENCE retired here 2026-08-22 (redundancy
 *  audit): `honestySentence` derives from claims alone and the VerdictCard directly below
 *  derives from the receipt — two derivations of "how did this go" on one page, and only the
 *  receipt one can say "delivered but not proven" (human override over an unverified oracle).
 *  One derivation, one render: the card's. `honestySentence` stays in lib/plain for the record;
 *  `badge` stays in the variant so heroState's contract is unchanged. */
export function DeliveredHero({ badge, rows }: { badge: HonestyBadge; rows: LedgerRow[] }) {
  void badge;
  return (
    <div className="flex max-w-4xl flex-col gap-3">
      {/* Status only, symmetric with TerminatedHero — the hero owns WHAT happened; the
          VerdictCard below owns how well it is proven. role="status" announces the settle. */}
      <p role="status" className="text-lg font-medium leading-relaxed text-success">
        Delivered.
      </p>
      <ClaimBar claims={heroClaims(rows)} />
    </div>
  );
}

/** Running: the heartbeat — who's working, for how long, and the claim bar
 *  waiting to fill. */
export function RunningHero({
  phase,
  startedAt,
  rows,
}: {
  phase: string;
  startedAt: number | null;
  rows: LedgerRow[];
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  const claims = heroClaims(rows);
  // The status sentence retired 2026-08-13 (owner): the STAGE is the live view —
  // repeating "who's working" up here was redundant. `now`/`startedAt` feed nothing
  // here anymore; total elapsed lives beside the mode switcher.
  void now;
  void startedAt;
  void phase;
  // `cancel run` deliberately does NOT live here any more (#116). It rendered only in this
  // variant, so the stop control vanished the moment the run paused for a decision — and a
  // thrashing run spends its life paused, which made the exit reachable only by first ANSWERING the
  // gate you were trying to escape. It now sits in RunHero's shared meta row, present for every
  // non-terminal variant.
  return (
    <div className="flex max-w-4xl flex-col gap-3">
      {claims.length > 0 && <ClaimBar claims={claims} dim />}
    </div>
  );
}

/** Terminated: the status sentence only. The REASON retired here 2026-08-22 (redundancy audit):
 *  it rendered up to four times on one page (hero, band paragraph, VerdictCard reason, record
 *  ProofRow). The hero states WHAT ended; the VerdictCard states WHY (classified) and the record
 *  ProofRow keeps the uncapped full text. Props stay so heroState's contract is unchanged. */
export function TerminatedHero({
  status,
  reason,
  reasonIsFull = false,
}: {
  status: string;
  reason: string;
  /** True when `reason` is the uncapped diagnosis text — kept for the variant contract. */
  reasonIsFull?: boolean;
}) {
  void reason;
  void reasonIsFull;
  return (
    <div className="flex max-w-4xl flex-col gap-1.5">
      <p
        role="status"
        className="text-lg font-medium leading-relaxed text-amber-600 dark:text-amber-400"
      >
        {TERMINATED[status] ?? `${status} — nothing was delivered.`}
      </p>
    </div>
  );
}
