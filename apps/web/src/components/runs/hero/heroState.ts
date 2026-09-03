/* Pure hero-state derivation: what the run page IS right now. Unit-tested in
   hero-state.test.ts; no React. */

import type { GatePayload, RunDiagnosis } from "../../../api/client";
import { honestyBadge, type HonestyBadge, type LedgerRow } from "../../../lib/ledger";
import { stopReason } from "../../../lib/plain";

export type HeroVariant =
  | { kind: "delivered"; badge: HonestyBadge }
  | { kind: "needs-you"; gate: GatePayload; flavor: "delivery" | "budget" }
  | { kind: "running"; phase: string; startedAt: number | null }
  /** `reasonIsFull`: the reason came from the diagnosis stop channels (uncapped),
   *  not the 80-char termination string — a full sentence must not get a fake "…". */
  | { kind: "terminated"; status: string; reason: string; reasonIsFull: boolean };

/** Precedence: a live parked gate always wins (the decision IS the page), then
 *  the settled verdicts, then honest failure, then "still working". */
export function deriveHeroVariant(input: {
  status: string; // live vocabulary (durable statuses pre-mapped by the page)
  gate: GatePayload | null;
  rows: LedgerRow[];
  phase: string;
  startedAt: number | null;
  terminationReason: string | null;
  diagnosis?: RunDiagnosis | null;
}): HeroVariant {
  const { status, gate, rows, phase, startedAt, terminationReason, diagnosis } = input;
  if (gate) {
    return { kind: "needs-you", gate, flavor: gate.action === "budget" ? "budget" : "delivery" };
  }
  if (rows.some((r) => r.kind === "delivered")) {
    return { kind: "delivered", badge: honestyBadge(rows) };
  }
  const full = stopReason(diagnosis)?.text;
  const terminated = rows.find((r) => r.kind === "terminated");
  if (terminated?.kind === "terminated") {
    return {
      kind: "terminated",
      status: terminated.status,
      reason: full || terminated.reason || terminationReason || "",
      reasonIsFull: Boolean(full),
    };
  }
  if (["incomplete", "error", "cancelled"].includes(status)) {
    return {
      kind: "terminated",
      status: status.toUpperCase(),
      reason: full || terminationReason || "",
      reasonIsFull: Boolean(full),
    };
  }
  return { kind: "running", phase, startedAt };
}
