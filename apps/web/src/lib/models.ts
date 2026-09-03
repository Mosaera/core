/* Pure derivations for the Settings › Models screen. Every value traces to a real
   API field — no synthesized capability data. The backend has NO per-model
   tool-calling / context-window metadata (that's a planned capability layer,
   docs/roadmap.md), so we deliberately never emit a "this model supports tools"
   verdict; we only surface what's truthfully knowable: price, locality, and the
   fixed tool *requirement* of the acting roles. Unit-tested in models-lib.test.ts. */

import type { CostModesState, Pricing, RoleBinding } from "../api/client";

/** Reconstruct the explicit per-mode overrides from a cost-modes state — the
 *  payload shape `saveCostModes` expects. Only cells the server marked
 *  `overridden` are sent; everything else falls back to the base binding. Used to
 *  re-send the full modes map when persisting a single edit. */
export function overridesOf(state: CostModesState): Record<string, Record<string, RoleBinding>> {
  const out: Record<string, Record<string, RoleBinding>> = {};
  for (const mode of state.available) {
    const map: Record<string, RoleBinding> = {};
    const roleMap = state.modes[mode] ?? {};
    for (const [role, cell] of Object.entries(roleMap)) {
      if (cell.overridden && cell.provider && cell.model) {
        map[role] = { provider: cell.provider, model: cell.model };
      }
    }
    out[mode] = map;
  }
  return out;
}

/** Human label for a cost-mode ("preset") id. The three built-in modes get
 *  operator-facing names; any other id passes through titlecased so a future
 *  server-added mode still renders. */
export function presetLabel(id: string): string {
  switch (id) {
    case "economy":
      return "Local · Free";
    case "balanced":
      return "Balanced";
    case "premium":
      return "Quality · Cloud";
    default:
      return id.charAt(0).toUpperCase() + id.slice(1);
  }
}

/** Display name for a provider id (used in selectors and the egress line). */
export function providerLabel(id: string): string {
  switch (id) {
    case "ollama":
      return "Ollama";
    case "openai":
      return "OpenAI";
    case "anthropic":
      return "Anthropic";
    default:
      return id.charAt(0).toUpperCase() + id.slice(1);
  }
}

// The acting roles need a tool-calling model (they mutate/execute: edit_file,
// write_file, run_tests). This mirrors the authoritative source — the per-role
// tool allowlist in packages/policies (ROLE_TOOL_ALLOWLIST) — as a UI-side fact
// so we can show the requirement without a round-trip. It is a requirement of the
// ROLE, never a claim about whether the bound model satisfies it.
const TOOL_ROLES = new Set(["coder", "tester"]);

/** Does this role require a tool-calling model? True only for the acting roles. */
export function roleNeedsTools(role: string): boolean {
  return TOOL_ROLES.has(role.toLowerCase());
}

/** Join names as a readable clause: "A" · "A & B" · "A, B & C". */
export function humanList(names: string[]): string {
  if (names.length === 0) return "";
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(", ")} & ${names[names.length - 1]}`;
}

export type PriceTone = "free" | "paid" | "unknown";

export interface PriceChip {
  text: string;
  tone: PriceTone;
}

/** The price chip for a role's bound model. Local models are free (no entry
 *  needed); a paid model shows its $/M in-out rate; a cloud model with no price
 *  set reads "no price" (its spend can't be counted until one is added). */
export function priceChip(model: string, isLocal: boolean, pricing: Pricing | undefined): PriceChip {
  if (isLocal) return { text: "free", tone: "free" };
  const entry = model ? pricing?.prices?.[model] : undefined;
  if (entry) return { text: `$${entry.input}/$${entry.output} per M`, tone: "paid" };
  return { text: "no price", tone: "unknown" };
}

/** Effective per-role binding for the egress calculation. */
export interface EffectiveBinding {
  role: string;
  label: string;
  provider: string;
  model: string;
}

export interface Egress {
  usesCloud: boolean;
  text: string;
}

/** The plain-language consequence line under the preset switcher, computed from
 *  the active preset's effective bindings. All-local is the calm default; any
 *  cloud role names which roles leave the box and to whom. No fabricated $/run —
 *  the global settings page has no run history to project from. */
export function egressConsequence(
  bindings: EffectiveBinding[],
  localProviderIds: Set<string>,
): Egress {
  const cloud = bindings.filter((b) => b.provider && !localProviderIds.has(b.provider));
  if (cloud.length === 0) {
    return { usesCloud: false, text: "All roles run locally — $0, nothing leaves your machine." };
  }
  const roles = humanList(cloud.map((b) => b.label));
  const providers = humanList([...new Set(cloud.map((b) => providerLabel(b.provider)))]);
  const verb = cloud.length === 1 ? "runs" : "run";
  return {
    usesCloud: true,
    text: `${roles} ${verb} on ${providers} — repo content is sent off-box to that provider.`,
  };
}

/** A truthful amber warning for a role row, or null. Triggers only on real,
 *  actionable conditions (never a fabricated capability verdict): no model bound,
 *  or a cloud model whose spend can't be counted because no price is set. */
export function roleWarning(
  provider: string,
  model: string,
  isLocal: boolean,
  pricing: Pricing | undefined,
): string | null {
  if (!model.trim()) return "No model selected — pick one for this role.";
  if (!isLocal && provider && !pricing?.prices?.[model]) {
    return "Cloud model with no price — its spend won't be counted until you add one.";
  }
  return null;
}

// Substrings marking a NON-chat Ollama model — mirrors the server's own filter for hosted
// providers' live lists (`_NON_CHAT_MARKERS` in mosaera_core.models). Conservative and
// name-based, since Ollama's /api/tags carries no capability metadata: a false negative (an
// embedding model that slips through) is a bad pick the Test step still catches; a false
// positive (hiding a real chat model) would be worse, so this only matches the clear case.
const _NON_CHAT_MARKERS = ["embed", "rerank"];

/** Whether `model` looks like a non-chat (embedding/rerank) model, and so should not be
 *  offered in a ROLE picker — every role here needs a chat/tool-calling model, and an
 *  embedding model bound to one silently produces nonsense output (O1-O3). */
export function isNonChatModel(model: string): boolean {
  const name = model.toLowerCase();
  return _NON_CHAT_MARKERS.some((m) => name.includes(m));
}

/** The exact copy-pasteable command to pull `model` on the local Ollama server — mirrors
 *  `preflight.check_ollama`'s fix string (`ollama pull <model>`) so the two surfaces never
 *  disagree about the fix for the same gap. */
export function ollamaPullFix(model: string): string {
  return `ollama pull ${model}`;
}

/** A caught fetch error's message, with a JSON `{"detail": "..."}` body (the FastAPI error
 *  shape) unwrapped to its plain sentence instead of shown as raw JSON (M1: a 403/422/5xx used
 *  to render `` `${status} ${statusText}: {"detail":"..."}` `` verbatim in the UI). Not
 *  model-specific, but every non-2xx settings write throws this exact shape (`json()` in
 *  api/client.ts), so it lives beside the other error-shape-aware helpers this screen uses. */
export function apiErrorDetail(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  const m = msg.match(/\{"detail":"(.*?)"\}/);
  return m ? m[1] : msg;
}

/** Whether a base URL points at a loopback host — i.e. traffic to it cannot leave
 *  this machine. Mirrors `models.is_loopback_url` server-side so the on-box checkbox
 *  can teach the rule inline. This is a UI AFFORDANCE ONLY: the API re-checks and
 *  refuses the save, so a bypass here changes nothing about the egress gate (ADR-0024).
 *  Tests the parsed hostname, never a substring, so `127.0.0.1.evil.com` is not loopback. */
export function isLoopbackUrl(raw: string | null | undefined): boolean {
  if (!raw?.trim()) return false;
  let host: string;
  try {
    host = new URL(raw.trim()).hostname.toLowerCase();
  } catch {
    return false;
  }
  const bare = host.replace(/^\[/, "").replace(/\]$/, ""); // unwrap IPv6 [::1]
  if (bare === "localhost" || bare === "::1") return true;
  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(bare);
  if (!v4) return false;
  const octets = v4.slice(1).map(Number);
  return octets.every((n) => n <= 255) && octets[0] === 127;
}
