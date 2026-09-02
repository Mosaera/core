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
    title: "Planner (Quincy)",
    fields: [
      { field: "doctrine_enabled", label: "Planning doctrine", widget: "toggle", help: "Inject Mosaera's trusted planning doctrine (+ per-project reference docs) into the PM." },
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
