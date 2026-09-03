/* Starter/quick-command prompts. Rendered as starter chips in the empty state
   OR as quick commands above the composer — never both at once (guardrail 6).

   Each chip maps to something the chat can genuinely do (10A honesty pass): propose an
   approvable backlog changeset (`_CHANGESET_OPS` in `pm/_chat_prompt.py`), answer from its own
   ledgers when `pm_chat_tools` is on (ADR-0111's `project_history` tool — open_work / failures /
   item_history / criteria_failed / orphaned; no cost or token data), or summarize the standing
   context it is always given. Two chips were CUT here, not reworded, because nothing behind them
   answers honestly: "Prepare the next run, but stop for approval before executing" — the chat
   never executes or authorizes a run (ADR-0105); and "Estimate the AI/API cost for the next run"
   — no tool or context field carries cost/token data, and the chat's own system prompt says so
   ("concepts like priority, cost, owner, or due dates" are not structured fields it can compute
   over). */

export const PM_PROMPTS: { label: string; prompt: string }[] = [
  { label: "Plan next sprint", prompt: "Plan the next sprint based on the current backlog." },
  { label: "Prioritize backlog", prompt: "Prioritize the backlog by customer impact." },
  { label: "Review what needs approval", prompt: "What needs my review right now?" },
  { label: "How we tend to fail", prompt: "How does this project tend to fail — by park cause and gate reason?" },
  { label: "Summarize progress", prompt: "Summarize progress since the project was created." },
];
