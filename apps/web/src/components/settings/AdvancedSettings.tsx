import { DeleteToolCard } from "./DeleteToolCard";
import { KnobForm, type KnobGroup } from "./KnobForm";

export const GROUPS: KnobGroup[] = [
  {
    title: "Quality gate",
    fields: [
      { field: "quality_revise_enabled", label: "Revise on low quality", widget: "toggle", help: "Loop the coder when a dimension scores below the floor." },
      { field: "quality_min", label: "Overall minimum score", widget: "number", help: "0–100." },
      { field: "quality_dim_floor", label: "Per-dimension floor", widget: "number", help: "0–100." },
      { field: "quality_max_revises", label: "Max quality revises", widget: "number" },
    ],
  },
  {
    title: "Review & hygiene loops",
    fields: [
      { field: "review_fix_enabled", label: "Auto-fix reviewer changes", widget: "toggle" },
      { field: "review_max_fixes", label: "Max review fixes", widget: "number" },
      { field: "hygiene_gate_enabled", label: "Hygiene gate (format/lint/types)", widget: "toggle" },
      { field: "hygiene_max_fixes", label: "Max hygiene fixes", widget: "number" },
      { field: "deliver_unverified", label: "Deliver without a passing validator", widget: "toggle", help: "Off = never ship a change no test could confirm." },
    ],
  },
  {
    title: "Agent step limits",
    fields: [
      { field: "coder_step_limit", label: "Coder step limit", widget: "number", help: "Tool calls before the coder is stopped." },
      { field: "reviewer_step_limit", label: "Reviewer step limit", widget: "number" },
      { field: "pm_step_limit", label: "PM step limit", widget: "number", help: "Read-tool calls before the planner is stopped." },
    ],
  },
  {
    // `doctrine_enabled` used to live in this group too. It's genuinely `internal`
    // server-side (config/_visibility.py) — an engine internal never otherwise reachable —
    // so it stays out. `pm_chat_tools` is NOT internal (a prior pass miscategorized it; see
    // that module's note) and `pm-steps.test.tsx` pins that it must have a real control here.
    title: "Planner (Quincy)",
    fields: [
      { field: "pm_chat_tools", label: "Let the PM check the record mid-chat", widget: "toggle", help: "Quincy can query this project's own runs and backlog while you talk, instead of answering from what the prompt happened to carry. Read-only, and only those records. Costs several model calls per reply." },
    ],
  },
  {
    title: "Sandbox",
    fields: [
      { field: "scan_enabled", label: "Security scan (secrets/SAST)", widget: "toggle" },
      { field: "sandbox_timeout", label: "Command timeout", widget: "number", unit: "s" },
      { field: "sandbox_install", label: "Dependency install phase", widget: "toggle", help: "Fetch deps before tests (Docker only opens egress for this)." },
      { field: "sandbox_install_timeout", label: "Install timeout", widget: "number", unit: "s" },
      { field: "sandbox_install_network", label: "Install network", widget: "select", help: "Docker network for the install phase." },
      { field: "sandbox_index_url", label: "Package index URL", widget: "text", help: "Optional pip index/proxy. Blank = default.", placeholder: "https://…" },
    ],
  },
  {
    title: "Ollama",
    fields: [
      { field: "ollama_base_url", label: "Ollama base URL", widget: "text", placeholder: "http://localhost:11434" },
      { field: "ollama_num_ctx", label: "Context window", widget: "number" },
      { field: "coder_num_ctx", label: "Coder context window", widget: "number", help: "Override for the coder. Blank = same as above." },
      { field: "ollama_timeout", label: "Request timeout", widget: "number", unit: "s" },
      {
        field: "ollama_keep_alive",
        label: "Model residency (keep-alive)",
        widget: "text",
        help: "How long Ollama keeps a model loaded after a call. Ollama's own default (5m) unloads mid-run on a guided approval wait and dumps the local prefix cache — a duration string Ollama parses (\"30m\", \"-1\" = never unload).",
        placeholder: "30m",
      },
    ],
  },
];

export function AdvancedSettings() {
  return (
    <div className="flex flex-col gap-12">
      <KnobForm
        title="Advanced"
        description="Automation loops, sandbox and model-runtime tuning. Defaults are sensible — change with intent."
        groups={GROUPS}
      />
      <DeleteToolCard />
    </div>
  );
}
