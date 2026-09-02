import type { GatePayload } from "../../../api/client";
import { BudgetGate } from "../BudgetGate";
import { GatePanel } from "../GatePanel";

/** The needs-you hero: when the run pauses for a person, the decision IS the
 *  page — nothing competes with it. The actual decision surfaces (GatePanel /
 *  BudgetGate) render unboxed via variant="hero"; their semantics are identical
 *  to the card form (same aria, buttons, prefill, budget note). */
export function DecisionHero({
  gate,
  flavor,
  busy,
  onDecide,
  autoAllowTests,
  onAutoAllowTests,
}: {
  gate: GatePayload;
  flavor: "delivery" | "budget";
  busy: boolean;
  onDecide: (approve: boolean, feedback: string) => void;
  autoAllowTests?: boolean;
  onAutoAllowTests?: (on: boolean) => void;
}) {
  return (
    <div className="max-w-4xl border-l-2 border-amber-500/60 pl-4">
      {flavor === "budget" ? (
        <BudgetGate gate={gate} busy={busy} onDecide={onDecide} variant="hero" />
      ) : (
        <GatePanel
          gate={gate}
          busy={busy}
          onDecide={onDecide}
          variant="hero"
          autoAllowTests={autoAllowTests}
          onAutoAllowTests={onAutoAllowTests}
        />
      )}
    </div>
  );
}
