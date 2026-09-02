import { KnobForm, type KnobGroup } from "./KnobForm";

const GROUPS: KnobGroup[] = [
  {
    title: "Run budgets",
    fields: [
      { field: "run_max_usd", label: "Max spend per run", widget: "number", unit: "$", help: "Parks for approval when crossed. Blank = no cap." },
      { field: "run_max_tokens", label: "Max tokens per run", widget: "number", help: "Blank = no cap." },
      { field: "run_max_tool_calls", label: "Max tool calls per run", widget: "number", help: "Blank = no cap." },
      { field: "run_max_seconds", label: "Wall-clock limit", widget: "number", unit: "s" },
      { field: "run_quota_per_day", label: "Runs per day (quota)", widget: "number", help: "Max runs/day per account. 0 = no cap. Over-quota submits get 429; admins exempt. Applies with no restart." },
    ],
  },
  {
    title: "Hard caps (cancel the run — not re-askable)",
    fields: [
      { field: "run_hard_max_usd", label: "Hard $ ceiling", widget: "number", unit: "$", help: "Cancels the run outright. Blank = none." },
      { field: "run_hard_max_tokens", label: "Hard token ceiling", widget: "number", help: "Blank = none." },
    ],
  },
  {
    title: "Iterations",
    fields: [
      { field: "max_iterations", label: "Default max iterations", widget: "number", help: "Plan→fix loops before the run gives up." },
      { field: "max_iterations_ceiling", label: "Iteration ceiling", widget: "number", help: "Hard upper bound a per-run value can't exceed." },
    ],
  },
  {
    title: "No-progress breaker",
    fields: [
      { field: "stall_detection_enabled", label: "Detect no-progress", widget: "toggle", help: "Stop honestly when the same failure repeats instead of looping to the cap." },
      { field: "stall_limit", label: "Identical outcomes before stopping", widget: "number" },
    ],
  },
  {
    title: "Transcript",
    fields: [
      { field: "stream_reasoning", label: "Stream agent reasoning", widget: "toggle", help: "Show each agent's thinking in the run transcript." },
    ],
  },
];

export function GeneralSettings() {
  return (
    <KnobForm
      title="General"
      description="Budgets, iteration limits and the no-progress breaker. Saved values apply to the next run — no restart."
      groups={GROUPS}
    />
  );
}
