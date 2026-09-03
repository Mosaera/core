// What a run STARTED with. Mirrors apps/api `runner/_provenance.py`: captured once at run start
// and never re-read, so a knob flipped later cannot retroactively re-describe a finished run.

/** Which optional agents/oracles were switched ON for a run. Recorded per run at start
 *  (apps/api `_base.py::controls`) so the UI can show the full cast from t=0 — including the
 *  ones that are off, which the roster previously could not distinguish from "not reached yet". */
export interface RunControls {
  tester_enabled?: boolean;
  critic_enabled?: boolean;
  scan_enabled?: boolean;
  oracle_coverage?: boolean;
  oracle_mutation_check?: boolean;
  reason_on_stall_enabled?: boolean;
  escalate_arm?: boolean;
  amendment_gate?: boolean;
}
