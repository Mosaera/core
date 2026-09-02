/* Pure derivation of the selected agent's work panel (#63): what each agent
   actually did, as data the WorkPanel renders in the shadcn/ai idiom — plan
   steps, chain-of-thought, terminal output, test results, tool milestones.
   Pending agents get an HONEST reason line, never an invented placeholder.
   Tested in engine-work.test.ts. */

import type { TranscriptEvent } from "../api/client";
import { activityLine } from "../components/runs/runActors";
import { AGENT_META, currentAgent, NODE_AGENT, type AgentId, type EngineInputs } from "./engine";
import type { LedgerRow } from "./ledger";
import { decisionOf, parseCriticVerdict } from "./runs";

export interface CotItem {
  text: string;
  state: "done" | "active";
  /** Small dim second line (a detail / source). */
  sub?: string;
}

export interface ToolItem {
  title: string;
  detail?: string;
  /** true = the call finished (green accent); false = still running (amber). */
  settled: boolean;
  /** >1 = a run of consecutive same-kind calls folded into one row ("read ×3"). */
  count?: number;
  /** The folded calls, for the row's own disclosure. */
  entries?: { title: string; detail?: string; settled: boolean }[];
}

export interface TestRow {
  passed: boolean;
  label: string;
  sub?: string;
}

export type WorkSection =
  | { kind: "prose"; title: string; text: string }
  | { kind: "cot"; title: string; items: CotItem[]; live?: boolean }
  | { kind: "terminal"; title: string; text: string }
  | { kind: "tests"; title: string; passed: number; failed: number; rows: TestRow[] }
  | { kind: "tools"; title: string; items: ToolItem[]; collapsed?: boolean }
  /** The delivery report, fetched lazily by the panel (a 404 is an honest answer). */
  | { kind: "report"; title: string; runId: string }
  | { kind: "empty"; reason: string };

export interface WorkModel {
  agent: AgentId;
  name: string;
  role: string;
  sections: WorkSection[];
  /** One-breath executive summary of what this agent did — derived, never generated. */
  summary?: string;
}

const MAX_COT = 12;
const MAX_TOOLS = 14;
const TERM_TAIL = 4000;

function eventsFor(inputs: EngineInputs, agent: AgentId): TranscriptEvent[] {
  return inputs.events.filter(
    (e) => NODE_AGENT[String(e.data?.node ?? e.node ?? "")] === agent,
  );
}

function thoughts(events: TranscriptEvent[], live: boolean): CotItem[] {
  const items: CotItem[] = [];
  for (const e of events) {
    if (e.type !== "thought") continue;
    const text = String(e.data?.text ?? "").trim();
    if (text) items.push({ text, state: "done" });
  }
  const tail = items.slice(-MAX_COT);
  if (live && tail.length > 0) tail[tail.length - 1].state = "active";
  return tail;
}

function tools(events: TranscriptEvent[]): ToolItem[] {
  // Raw calls first…
  const raw: { kind: string; title: string; detail?: string; settled: boolean }[] = [];
  for (const e of events) {
    if (e.type !== "activity") continue;
    const d = e.data ?? {};
    const kind = String(d.kind ?? "");
    if (!kind) continue;
    raw.push({
      kind,
      title: activityLine(kind, d.detail == null ? undefined : String(d.detail)),
      detail: d.result == null ? undefined : String(d.result),
      settled: d.result != null,
    });
  }
  // …then CONSECUTIVE same-kind runs fold into one row ("read ×7") that carries its
  // individual calls for the row's own disclosure — a long crawl becomes a summary.
  const items: ToolItem[] = [];
  for (const r of raw.slice(-MAX_TOOLS)) {
    const last = items[items.length - 1];
    if (last && (last as { kind?: string }).kind === r.kind) {
      last.count = (last.count ?? 1) + 1;
      last.entries!.push({ title: r.title, detail: r.detail, settled: r.settled });
      last.title = `${activityLine(r.kind)} ×${last.count}`;
      last.detail = undefined;
      last.settled = last.entries!.every((x) => x.settled);
    } else {
      items.push({
        ...r,
        entries: [{ title: r.title, detail: r.detail, settled: r.settled }],
      } as ToolItem);
    }
  }
  return items;
}

function lastUpdateText(
  events: TranscriptEvent[],
  node: string,
  field: string,
): string {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i];
    if (e.type !== "update") continue;
    if (String(e.data?.node ?? e.node ?? "") !== node) continue;
    const v = (e.data?.update as Record<string, unknown> | undefined)?.[field];
    if (typeof v === "string" && v.trim()) return v;
  }
  return "";
}

/** Plan text → step items (numbered/dashed lines become steps; else one block). */
export function planSteps(text: string): CotItem[] {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => /^(\d+[.)]\s+|[-*]\s+)/.test(l))
    .map((l) => l.replace(/^(\d+[.)]\s+|[-*]\s+)/, ""));
  if (lines.length >= 2) return lines.slice(0, 10).map((text) => ({ text, state: "done" }));
  return [];
}

function pendingReason(agent: AgentId, inputs: EngineInputs): string {
  switch (agent) {
    case "quincy":
      return "The run hasn't started planning yet.";
    case "architect":
      return "Waits for the plan — the design shapes the approach before tests or code exist.";
    case "proctor":
      return "Waits for the design — the acceptance tests are authored before any code exists.";
    case "forge":
      return "Waits for the plan. The Smith only builds what the Chart-Maker scoped.";
    case "vera":
      return "Waits for a build. The checks run after every change the Smith makes.";
    case "rook":
      return "Waits for green checks. The Tribune reads the diff with fresh eyes and no stake in the code.";
    case "critic":
      return "Waits for the Tribune's verdict. The Critic never watches the build — it judges only the final evidence.";
    case "you":
      return inputs.live
        ? "The delivery gate hasn't opened. When it does, nothing ships until you approve."
        : "The gate never opened — no approval was possible.";
    case "drift":
      return inputs.live
        ? "No commit, no receipt yet. Drift only moves after your approval at the gate."
        : "Nothing was delivered.";
  }
}

/** The agent's event stream split into PASSES: a pass ends when another agent's
 *  event lands (Build → checks → Build again = two passes for the Smith). */
export function agentPasses(inputs: EngineInputs, agent: AgentId): TranscriptEvent[][] {
  const passes: TranscriptEvent[][] = [];
  let cur: TranscriptEvent[] | null = null;
  for (const e of inputs.events) {
    const a = NODE_AGENT[String(e.data?.node ?? e.node ?? "")];
    if (a === agent) {
      if (!cur) {
        cur = [];
        passes.push(cur);
      }
      cur.push(e);
    } else if (a !== undefined && cur) {
      cur = null;
    }
  }
  return passes;
}

/** Honest one-breath summary per agent, composed only from recorded evidence. */
function summarize(agent: AgentId, own: TranscriptEvent[], sections: WorkSection[]): string | undefined {
  const first = (kind: WorkSection["kind"]) => sections.find((x) => x.kind === kind);
  const clamp = (t: string) => {
    // First line that actually SAYS something: skip heading-only/marker lines and
    // strip markdown noise ("## Approach" is not a summary).
    const line =
      t
        .split("\n")
        .map((l) => l.replace(/^#{1,4}\s+/, "").replace(/\*\*/g, "").trim())
        .find((l) => l.length > 12) ?? "";
    return line.length > 160 ? `${line.slice(0, 157)}…` : line;
  };
  const turns = own.filter((e) => e.type === "thought").length;
  const calls = own.filter((e) => e.type === "activity").length;
  switch (agent) {
    case "quincy": {
      const plan = first("cot");
      return plan && plan.kind === "cot"
        ? `Broke the task into ${plan.items.length} steps.`
        : undefined;
    }
    case "architect": {
      const d = first("prose");
      return d && d.kind === "prose" ? clamp(d.text) || undefined : undefined;
    }
    case "proctor": {
      const t = first("tools");
      return t && t.kind === "tools"
        ? `Authored ${t.items.length} protected acceptance test${t.items.length === 1 ? "" : "s"} the coder cannot edit.`
        : undefined;
    }
    case "forge":
      return calls > 0 || turns > 0
        ? `Implemented the change — ${turns} reasoning turn${turns === 1 ? "" : "s"}, ${calls} tool call${calls === 1 ? "" : "s"}.`
        : undefined;
    case "vera": {
      const t = first("tests");
      if (t && t.kind === "tests") return `Check runs: ${t.passed} green, ${t.failed} failed.`;
      return undefined;
    }
    case "rook": {
      const r = first("prose");
      return r && r.kind === "prose" ? clamp(r.text) || undefined : undefined;
    }
    case "critic": {
      const c = first("prose");
      return c && c.kind === "prose" ? clamp(c.text) || undefined : undefined;
    }
    case "drift": {
      const t = first("tools");
      if (t && t.kind === "tools" && t.items[0]) return `Delivered — ${t.items[0].title}.`;
      return undefined;
    }
    default:
      return undefined;
  }
}

/** The model-authored plain-English summary persisted at park/finalize (an
 *  `agent_summaries` decision). Display narration only — never evidence. */
function authoredSummary(detail: EngineInputs["detail"], agent: AgentId): string | undefined {
  const raw = decisionOf(detail ?? undefined, "agent_summaries");
  if (!raw) return undefined;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const v = parsed[agent];
    return typeof v === "string" && v.trim() ? v.trim() : undefined;
  } catch {
    return undefined;
  }
}

export function deriveWork(
  agent: AgentId,
  inputs: EngineInputs,
  rows: LedgerRow[] = [],
  /** Restrict the event-derived sections to one PASS (agentPasses slice). */
  passEvents?: TranscriptEvent[],
): WorkModel {
  const meta = AGENT_META[agent];
  const detail = inputs.detail ?? undefined;
  const own = passEvents ?? eventsFor(inputs, agent);
  const isCurrent = currentAgent(inputs) === agent;
  const sections: WorkSection[] = [];

  switch (agent) {
    case "quincy": {
      // Quincy thinks too — its plan/design turns were emitted but never rendered
      // (measured live 2026-08-13: 31 thought events, zero on screen).
      const qcot = thoughts(own, isCurrent);
      if (qcot.length > 0)
        sections.push({ kind: "cot", title: "Chain of thought", items: qcot, live: isCurrent });
      const brief = rows.find((r) => r.kind === "brief");
      if (brief?.kind === "brief" && brief.text)
        sections.push({ kind: "prose", title: "The request", text: brief.text });
      const ask = rows.find((r) => r.kind === "clarification");
      if (ask?.kind === "clarification") {
        const q = ask.record;
        const question = `Couldn't bind a check to: “${q.claim_text}” — ${q.why_unbindable}`;
        const answer =
          q.status === "resolved" ? (q.resolution ?? "") : q.status === "dismissed" ? "(dismissed)" : "";
        sections.push({
          kind: "prose",
          title: q.status === "open" ? "Question — open" : "Question — answered",
          text: answer ? `${question}\n\n→ ${answer}` : question,
        });
      }
      const plan = decisionOf(detail, "plan") || lastUpdateText(inputs.events, "plan", "plan");
      const steps = planSteps(plan);
      if (steps.length > 0) sections.push({ kind: "cot", title: "Plan", items: steps });
      else if (plan) sections.push({ kind: "prose", title: "Plan", text: plan });
      break;
    }
    case "architect": {
      const acot = thoughts(own, isCurrent);
      if (acot.length > 0)
        sections.push({ kind: "cot", title: "Chain of thought", items: acot, live: isCurrent });
      const design =
        decisionOf(detail, "design") || lastUpdateText(inputs.events, "design", "design");
      if (design) sections.push({ kind: "prose", title: "Design", text: design });
      break;
    }
    case "proctor": {
      const pcot = thoughts(own, isCurrent);
      if (pcot.length > 0)
        sections.push({ kind: "cot", title: "Chain of thought", items: pcot, live: isCurrent });
      const tests = own
        .filter((e) => e.type === "update")
        .flatMap((e) => {
          const v = (e.data?.update as Record<string, unknown> | undefined)?.authored_tests;
          return Array.isArray(v) ? v.map((x) => String(x)) : [];
        });
      if (tests.length > 0)
        sections.push({
          kind: "tools",
          title: "Acceptance tests (protected — the coder cannot edit these)",
          items: tests.map((t) => ({ title: t, settled: true })),
        });
      break;
    }
    case "forge": {
      const cot = thoughts(own, isCurrent);
      if (cot.length > 0)
        sections.push({ kind: "cot", title: "Chain of thought", items: cot, live: isCurrent });
      const t = tools(own);
      if (t.length > 0)
        sections.push({ kind: "tools", title: "Tool calls", items: t, collapsed: true });
      break;
    }
    case "vera": {
      const out =
        lastUpdateText(inputs.events, "test", "test_output") ||
        (detail?.test_results ?? []).map((r) => r.output).filter(Boolean).slice(-1)[0] ||
        "";
      if (out)
        sections.push({ kind: "terminal", title: "Validation output", text: out.slice(-TERM_TAIL) });
      const runs: TestRow[] = [];
      let i = 0;
      for (const e of inputs.events) {
        if (e.type !== "update") continue;
        if (String(e.data?.node ?? e.node ?? "") !== "test") continue;
        const u = (e.data?.update ?? {}) as Record<string, unknown>;
        if (typeof u.tests_passed !== "boolean") continue;
        i += 1;
        runs.push({
          passed: u.tests_passed,
          label: `run ${i}`,
          sub: u.tests_passed ? "all green" : "failed — sent back to Forge",
        });
      }
      if (runs.length === 0 && (detail?.test_results ?? []).length > 0) {
        for (const [j, r] of (detail?.test_results ?? []).entries())
          runs.push({ passed: r.passed, label: `run ${j + 1}` });
      }
      if (runs.length > 0)
        sections.push({
          kind: "tests",
          title: "Check runs",
          passed: runs.filter((r) => r.passed).length,
          failed: runs.filter((r) => !r.passed).length,
          rows: runs,
        });
      const hygiene = own
        .filter(
          (e) => e.type === "update" && String(e.data?.node ?? e.node ?? "") === "hygiene",
        )
        .flatMap((e) => {
          const v = (e.data?.update as Record<string, unknown> | undefined)?.hygiene_findings;
          return Array.isArray(v) ? v.map((x) => String(x)) : [];
        })
        .join("\n");
      const scan =
        decisionOf(detail, "scan") || lastUpdateText(inputs.events, "scan", "findings_text");
      if (hygiene) sections.push({ kind: "prose", title: "Hygiene findings", text: hygiene });
      if (scan) sections.push({ kind: "prose", title: "Security scan", text: scan });
      break;
    }
    case "rook": {
      const review =
        decisionOf(detail, "review") || lastUpdateText(inputs.events, "review", "review");
      if (review) sections.push({ kind: "prose", title: "Review", text: review });
      const cot = thoughts(own, isCurrent);
      if (cot.length > 0)
        sections.push({ kind: "cot", title: "Chain of thought", items: cot, live: isCurrent });
      const t = tools(own);
      if (t.length > 0)
        sections.push({
          kind: "tools",
          title: "Tool calls (read-only — the Tribune cannot edit code)",
          items: t,
          collapsed: true,
        });
      break;
    }
    case "critic": {
      const ov = parseCriticVerdict(detail);
      if (ov) {
        const head = ov.vetoed ? "VETOED" : "No veto";
        sections.push({
          kind: "prose",
          title: "Held-out verdict",
          text: ov.reason ? `${head} — ${ov.reason}` : head,
        });
      }
      break;
    }
    case "you": {
      const answers = detail?.approvals ?? [];
      if (answers.length > 0)
        sections.push({
          kind: "tools",
          title: "Your decisions",
          items: answers.map((a) => ({
            title: `${a.action || "deliver"} — ${a.approved ? "approved" : "sent back"}`,
            detail: a.feedback || undefined,
            settled: true,
          })),
        });
      break;
    }
    case "drift": {
      if (detail?.commit_sha)
        sections.push({
          kind: "tools",
          title: "Delivery",
          items: [
            { title: `commit ${detail.commit_sha.slice(0, 8)}`, detail: detail.branch, settled: true },
            ...(detail.receipt_id
              ? [{ title: "receipt sealed", detail: detail.receipt_id.slice(0, 16), settled: true }]
              : []),
          ],
        });
      const diff = detail?.repo_changes?.[0]?.diff ?? "";
      if (diff) sections.push({ kind: "terminal", title: "What changed (diff)", text: diff.slice(-TERM_TAIL) });
      if (detail?.commit_sha)
        sections.push({ kind: "report", title: "Delivery report", runId: detail.id });
      break;
    }
  }

  if (sections.length === 0) sections.push({ kind: "empty", reason: pendingReason(agent, inputs) });
  return {
    agent,
    name: meta.name,
    role: meta.role,
    sections,
    summary: authoredSummary(inputs.detail, agent) ?? summarize(agent, own, sections),
  };
}
