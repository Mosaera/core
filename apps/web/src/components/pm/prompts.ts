/* Starter/quick-command prompts. Rendered as starter chips in the empty state
   OR as quick commands above the composer — never both at once (guardrail 6). */

export const PM_PROMPTS: { label: string; prompt: string }[] = [
  { label: "Plan next sprint", prompt: "Plan the next sprint based on the current backlog." },
  { label: "Prioritize backlog", prompt: "Prioritize the backlog by customer impact." },
  { label: "Review what needs approval", prompt: "What needs my review right now?" },
  { label: "Estimate AI cost", prompt: "Estimate the AI/API cost for the next run." },
  {
    label: "Prepare next run",
    prompt: "Prepare the next run, but stop for approval before executing.",
  },
  { label: "Summarize progress", prompt: "Summarize progress since the project was created." },
];
