import { KnobForm, type KnobGroup } from "./KnobForm";

// The autonomy cluster + mr_granularity — GENERAL_KNOBS that had no Settings home (issue #36).
// Every field here is a real server knob; KnobForm renders each from its server-declared
// kind/choices (enum → <Select>, never free text — the hard rule).
const GROUPS: KnobGroup[] = [
  {
    title: "Delivery gate",
    fields: [
      {
        field: "autonomous_verified",
        label: "Verify autonomous runs",
        widget: "toggle",
        help: "Gate an autonomous delivery on the tester's spec-derived acceptance suite (the independent oracle the reviewer/own-suite can't be). This is a MASTER switch: while it is on, every knob marked \u201cforced when autonomous\u201d below is turned on for autonomous runs regardless of its own setting (your stored value still applies to guided and ad-hoc runs).",
      },
      {
        field: "allow_cloud_egress",
        label: "Allow cloud egress",
        widget: "toggle",
        help: "Off = autonomous runs stay LOCAL-ONLY. On lets autonomous escalation use cloud models (sends repo content off-box), but only when the model is also priced so the USD cap can bound it.",
      },
    ],
  },
  {
    title: "Sweep & merge requests",
    fields: [
      {
        field: "resilient_sweep",
        label: "Resilient sweep",
        widget: "toggle",
        help: "A stuck backlog item is deferred (surfaced with its reason) and the sweep keeps delivering the rest, instead of halting the whole project.",
      },
      {
        field: "resilient_recuration",
        label: "Re-curate stuck items",
        widget: "toggle",
        help: "Before deferring, let Quincy try to split / re-scope a stuck item (an extra LLM call).",
      },
      {
        field: "backlog_spec_lint",
        label: "Lint generated backlogs",
        widget: "toggle",
        help: "Deterministic acceptance check on a freshly-generated backlog (exact-value over-specification, refactor-phrase collisions, near-duplicates) + one Quincy re-curate pass when findings exist.",
      },
      {
        field: "disposition_gap_close",
        label: "Convert verifiable parks to ships",
        widget: "toggle",
        help: "When an autonomous item parks because no independent oracle vouched (its tests are the coder's own), Quincy authors an independent asserting test and re-runs the real sandboxed oracle — green + mutation-proven ships verified, else stays parked. Never an LLM green-light.",
      },
      {
        field: "auto_open_mr",
        label: "Auto-open merge request",
        widget: "toggle",
        help: "When an autonomous sweep fully delivers a backlog, open the project MR — never merges; a human still merges.",
      },
      {
        field: "mr_granularity",
        label: "Merge-request granularity",
        widget: "select",
        help: "item = one stacked, revertable MR per backlog item; project = one whole-project MR. Applies when auto-open is on.",
      },
    ],
  },
  {
    // Moved here from the Delivery page (redundancy audit 2026-08-22): a global knob does not
    // belong on a project-scoped operations surface, where editing it for one project silently
    // changed every other. This is the knob's ONLY render in the product — Delivery links here.
    title: "Branch destruction",
    fields: [
      {
        field: "member_branch_delete",
        label: "Members may delete branches",
        widget: "toggle",
        help: "Off = pruning and deleting branches is admin-only. Installing the project token is admin-gated, so spending it irreversibly on the repository is too. When on, a member may still only delete a branch GitLab reports as merged.",
      },
    ],
  },
  {
    title: "Escalation & stall recovery",
    fields: [
      {
        field: "max_escalations",
        label: "Max supervisor escalations",
        widget: "number",
        help: "Re-scope loops before an autonomous run gives up.",
      },
      {
        field: "escalate_arm",
        label: "Ask the operator on an oracle conflict",
        widget: "toggle",
        help: "When the coder proves it cannot meet a test it is forbidden to edit, stop the run instead of re-scoping it back at the same wall, and raise a question on the backlog item. Re-scoping cannot fix an acceptance bar — only you can. Never edits a test and never ships.",
      },
      {
        field: "amendment_gate",
        label: "Let the operator authorize amending a blocked test",
        widget: "toggle",
        help: "Goes further than the row above: instead of only stopping, the escalation offers you the specific delivered test that is in the way. Authorize one and the TESTER — never the coder — rewrites it once, so an item that CHANGES behaviour can finish instead of deadlocking against the test asserting the old behaviour. Needs the test-first tester on.",
      },
      {
        field: "coder_test_repeat_limit",
        label: "Coder test-repeat limit",
        widget: "number",
        help: "Identical failing test-fix attempts before the no-progress breaker trips.",
      },
      {
        field: "reason_on_stall_enabled",
        label: "Reason on stall",
        widget: "toggle",
        help: "On the first no-progress trip, run one bounded reasoning pass to try a different approach before parking.",
      },
      { field: "max_reason_attempts", label: "Max reason attempts", widget: "number" },
      {
        field: "model_escalation_enabled",
        label: "Model escalation",
        widget: "toggle",
        help: "On a stuck run, bump the culprit role one model tier along your escalation ladder.",
      },
      { field: "max_model_escalations", label: "Max model escalations", widget: "number" },
    ],
  },
  {
    title: "Tester & oracle",
    fields: [
      {
        field: "tester_enabled",
        label: "Test-first tester (Proctor)",
        widget: "toggle",
        help: "Author spec-derived acceptance tests before the coder implements.",
      },
      { field: "tester_step_limit", label: "Tester step limit", widget: "number" },
      {
        field: "oracle_coverage",
        label: "Coverage oracle",
        widget: "toggle",
        help: "Credit a change only when its changed lines are covered by an asserting test (runtime coverage).",
      },
      {
        field: "oracle_mutation_check",
        label: "Oracle mutation check",
        widget: "toggle",
        help: "Verify the authored suite actually catches a mutation in the changed code (not a tautological suite).",
      },
    ],
  },
];

export function AutonomySettings() {
  return (
    <KnobForm
      title="Autonomy"
      description="How far a run acts on its own — the autonomous correctness gate, stall/model escalation, the tester & oracle, and autonomous delivery. Conservative defaults; loosen with intent."
      groups={GROUPS}
    />
  );
}
