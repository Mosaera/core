/* Pure derivation for the Ledger view (#63): (durable record, transcript events,
   backlog item, live stream state) → chronological LedgerRow[]. No React.

   Chronology honesty: decision created_at values cluster at persist time and NEVER
   drive ordering. Real clocks are transcript event `ts` (server ms), approval
   created_at (written at gate time), and the run row's created_at/finished_at; the
   overall sequence is the fixed structural order of a run's life. Rows are recomputed
   wholesale from inputs on every change — there is no stateful merge, so a live gate
   row can never duplicate its later durable form. Unit-tested in ledger-lib.test.ts. */

import type {
  BacklogClaim,
  BacklogItem,
  GatePayload,
  ItemClarification,
  OutcomeVerdict,
  RunClaimRow,
  RunDetail,
  TranscriptEvent,
} from "../api/client";
import { receiptFromDetail, receiptFromGate, type ReceiptData } from "../components/runs/ReceiptCard";
import type { TranscriptItem } from "../hooks/useRunStream";
import { normalizeCriticVerdict, type HonestyKind } from "./plain";
import { decisionOf, lastMatch, parseCriticVerdict } from "./runs";

/* ------------------------------------------------------------------- claims */

/** A claim row normalized across its two sources (the durable run ledger wins;
 *  the item's derived claims are the pre-run fallback). */
export interface LedgerClaim {
  id: string;
  text: string;
  provenance: string; // ENTAILED | REPOSITORY_INVARIANT | INFERRED
  oracleKind: string;
  material: boolean;
  /** Evaluated verdict when the durable ledger is the source; "" pre-run. */
  verdict: string;
  oracleRef: string;
}

function fromRunClaims(rows: RunClaimRow[]): LedgerClaim[] {
  return rows.map((r) => ({
    id: r.claim_id,
    text: r.text,
    provenance: r.provenance ?? "",
    oracleKind: r.oracle_kind ?? "",
    material: r.material !== false,
    verdict: r.verdict,
    oracleRef: r.oracle_ref,
  }));
}

function fromItemClaims(rows: BacklogClaim[]): LedgerClaim[] {
  return rows.map((r) => ({
    id: r.id,
    text: r.text,
    provenance: r.provenance ?? "",
    oracleKind: r.oracle_kind ?? "",
    material: r.material !== false,
    verdict: "",
    oracleRef: "",
  }));
}

/* --------------------------------------------------------------------- rows */

interface RowBase {
  key: string;
  /** Epoch ms, or null when no honest clock exists for this row (rendered as —). */
  ts: number | null;
}

export type LedgerRow =
  | (RowBase & { kind: "brief"; actor: string; title: string; text: string })
  | (RowBase & {
      kind: "decomposition";
      claims: LedgerClaim[];
      source: "run" | "item";
      /** Row-attached artifacts (#63 redesign): the plan/design behind the decomposition. */
      planText: string;
      designText: string;
    })
  | (RowBase & { kind: "clarification"; record: ItemClarification; interactive: boolean })
  | (RowBase & { kind: "run-start"; runId: string; boundCount: number })
  | (RowBase & {
      kind: "gate";
      /** The live interrupt payload — present ONLY while this gate awaits a person. */
      gate: GatePayload | null;
      interactive: boolean;
      receipt: ReceiptData | null;
      /** The first failing validation step, when one explains the park. */
      failingStep: { name: string; output: string } | null;
      /** The full validation output (all steps), disclosed on demand — last gate only. */
      validationOutput: string;
    })
  | (RowBase & { kind: "operator-answer"; approved: boolean; feedback: string })
  | (RowBase & {
      kind: "review";
      reviewerVerdict: string;
      critic: OutcomeVerdict | null;
      counts: { supported: number; insufficient: number; discarded: number };
      /** The full reviewer text, disclosed on demand. */
      reviewText: string;
    })
  | (RowBase & {
      kind: "delivered";
      claims: LedgerClaim[];
      receipt: ReceiptData | null;
      /** Row-attached artifacts: the change itself + scan findings; the report is
       *  lazily fetched by runId (a 404 stays the honest answer). */
      runId: string;
      diff: string;
      scanText: string;
    })
  | (RowBase & { kind: "terminated"; status: string; reason: string })
  | (RowBase & {
      kind: "seal";
      runId: string;
      receiptId: string | null;
      finishedAt: string | null;
      engineVersion: string | null;
      /** The exact hashed inputs, so the checksum is re-computable in the browser:
       *  sha256(runId \n commitSha \n engineVersion \n receiptPayload). */
      commitSha: string;
      receiptPayload: string | null;
    });

export interface LedgerInput {
  detail?: RunDetail;
  item?: BacklogItem;
  events?: TranscriptEvent[];
  live?: { gate: GatePayload | null; status: string; startedAt: number | null };
}

const TERMINAL_STATUSES = new Set(["APPROVED", "NOT APPROVED", "INCOMPLETE", "CANCELLED", "ERROR"]);

function parseMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

/** The first failing validation step, from the per-step evidence rows. */
function failingStep(detail: RunDetail | undefined): { name: string; output: string } | null {
  const failed = detail?.test_results.find((r) => !r.passed);
  if (!failed) return null;
  const m = /^\[step ([^:]+):/.exec(failed.output);
  return { name: m?.[1] ?? "validation", output: failed.output };
}

export function deriveLedger(input: LedgerInput): LedgerRow[] {
  const { detail, item, events = [], live } = input;
  const rows: LedgerRow[] = [];
  const status = detail?.status ?? "";
  const isLive = live != null && !TERMINAL_STATUSES.has(status);

  // 1 · The operator's brief — what all downstream claims are entailed from.
  const briefText = [item?.description, item?.acceptance].filter(Boolean).join("\n\n");
  const briefTitle = item?.title ?? detail?.task ?? "";
  if (briefTitle || briefText) {
    rows.push({
      kind: "brief",
      key: "brief",
      ts: parseMs(item ? null : detail?.created_at) ?? null,
      actor: "Operator",
      title: briefTitle,
      text: briefText || (item ? "" : ""),
    });
  }

  // 2 · Quincy's decomposition into claims. Durable run ledger wins (it is what the
  // run actually bound); the item's derived claims are the pre-run view.
  const runClaims = detail?.claims ?? [];
  const claims: LedgerClaim[] =
    runClaims.length > 0 ? fromRunClaims(runClaims) : fromItemClaims(item?.claims ?? []);
  if (claims.length > 0) {
    rows.push({
      kind: "decomposition",
      key: "decomposition",
      ts: null, // claim minting has no honest per-claim clock
      claims,
      source: runClaims.length > 0 ? "run" : "item",
      planText: decisionOf(detail, "plan"),
      designText: decisionOf(detail, "design"),
    });
  }

  // 3 · The intake clarification exchange (retained record, #63).
  const record = item?.clarification_record ?? item?.clarification ?? null;
  if (record) {
    rows.push({
      kind: "clarification",
      key: "clarification",
      ts: parseMs(record.asked_at),
      record,
      interactive: record.status === "open" && isLive,
    });
  }

  // 4 · Run start. First transcript event is the honest first tick; else the row stamp.
  if (detail || live) {
    const firstTs = events.length > 0 ? events[0].ts : null;
    rows.push({
      kind: "run-start",
      key: "run-start",
      ts: firstTs ?? parseMs(detail?.created_at) ?? (live?.startedAt ? live.startedAt * 1000 : null),
      runId: detail?.id ?? "",
      boundCount: claims.filter((c) => c.material).length,
    });
  }

  // 5 · Gate visits + operator answers. Interrupt events carry the honest park times;
  // approvals (real gate-time stamps) pair index-wise. The receipt renders on the LAST
  // gate — it is the verdict of the visit that settled the run.
  const interrupts = events.filter((e) => e.type === "interrupt");
  const approvals = detail?.approvals ?? [];
  const durableReceipt = receiptFromDetail(detail);
  const liveGate = isLive && live?.gate && live.gate.action !== "budget" ? live.gate : null;
  const gateCount = Math.max(interrupts.length, approvals.length, liveGate ? 1 : 0);
  for (let i = 0; i < gateCount; i++) {
    const isLast = i === gateCount - 1;
    const answered = i < approvals.length;
    const interactive = Boolean(liveGate && isLast && !answered);
    rows.push({
      kind: "gate",
      key: `gate-${i}`,
      ts: interrupts[i]?.ts ?? parseMs(approvals[i]?.created_at),
      gate: interactive ? liveGate : null,
      interactive,
      receipt: interactive
        ? (receiptFromGate(liveGate ?? undefined) ?? null)
        : isLast
          ? (durableReceipt ?? null)
          : null,
      failingStep: isLast ? failingStep(detail) : null,
      validationOutput: isLast
        ? (detail?.test_results ?? []).map((r) => r.output).join("\n\n")
        : "",
    });
    if (answered) {
      rows.push({
        kind: "operator-answer",
        key: `answer-${i}`,
        ts: parseMs(approvals[i].created_at),
        approved: approvals[i].approved,
        feedback: approvals[i].feedback,
      });
    }
  }

  // 6 · The review verdict (the held-out critic's per-claim judgement, #61).
  const critic = parseCriticVerdict(detail) ?? null;
  if (critic || durableReceipt?.reviewerVerdict) {
    // Normalized ONCE (plain.ts): the backend emits INSUFFICIENT_EVIDENCE; the old
    // exact-match on "INSUFFICIENT" silently counted zero.
    const verdicts = (critic?.rows ?? []).map((r) => normalizeCriticVerdict(r.verdict));
    rows.push({
      kind: "review",
      key: "review",
      ts: null,
      reviewerVerdict: durableReceipt?.reviewerVerdict ?? "",
      critic,
      counts: {
        supported: verdicts.filter((v) => v === "SUPPORTED").length,
        insufficient: verdicts.filter((v) => v === "INSUFFICIENT_EVIDENCE").length,
        discarded: verdicts.filter((v) => v === "DISCARDED").length,
      },
      reviewText: decisionOf(detail, "review"),
    });
  }

  // 7 · The close: delivered (green) or an honest non-delivery.
  const finishedTs = parseMs(detail?.finished_at);
  if (status === "APPROVED") {
    rows.push({
      kind: "delivered",
      key: "delivered",
      ts: finishedTs,
      claims: claims.filter((c) => c.verdict !== ""),
      receipt: durableReceipt ?? null,
      runId: detail?.id ?? "",
      diff: detail?.repo_changes[0]?.diff ?? "",
      scanText: decisionOf(detail, "scan"),
    });
  } else if (TERMINAL_STATUSES.has(status)) {
    rows.push({
      kind: "terminated",
      key: "terminated",
      ts: finishedTs,
      status,
      reason: detail?.termination_reason ?? "",
    });
  }

  // 8 · The seal — only on a settled record, only from stamped facts.
  if (detail && TERMINAL_STATUSES.has(status)) {
    rows.push({
      kind: "seal",
      key: "seal",
      ts: finishedTs,
      runId: detail.id,
      receiptId: detail.receipt_id ?? null,
      finishedAt: detail.finished_at ?? null,
      engineVersion: detail.engine_version ?? null,
      commitSha: detail.commit_sha ?? "",
      receiptPayload:
        lastMatch(detail.decisions, (d) => d.kind === "receipt")?.content ?? null,
    });
  }

  return rows;
}

/* --------------------------------------------------- durable → transcript items */

const asList = (v: unknown): string =>
  Array.isArray(v) ? v.map((x) => String(x)).join("\n") : "";

/** The single source for per-node body text pulled out of `update` payloads — the
 *  live stream (useRunStream) and the durable replay below must extract identically,
 *  so this map is shared. Raw passthrough of recorded fields only: no verdict logic
 *  lives here (that stays in plain.ts / the parsers). Nodes absent from this map
 *  (e.g. `fix`, which records only its iteration count) have no text to surface. */
export const NODE_TEXT: Record<string, (u: Record<string, unknown>) => string> = {
  plan: (u) => String(u.plan ?? ""),
  design: (u) => String(u.design ?? ""),
  author_tests: (u) => asList(u.authored_tests),
  test: (u) => String(u.test_output ?? ""),
  hygiene: (u) => asList(u.hygiene_findings),
  scan: (u) => String(u.findings_text ?? ""),
  review: (u) => String(u.review ?? ""),
  critic: (u) => {
    const ov = u.outcome_verdict as { vetoed?: boolean; reason?: string } | null | undefined;
    if (!ov || typeof ov !== "object") return "";
    const head = ov.vetoed ? "vetoed" : "no veto";
    return ov.reason ? `${head}: ${ov.reason}` : head;
  },
  gate: (u) => {
    const gd = u.gate_decision as { reasons?: unknown } | null | undefined;
    return gd && typeof gd === "object" ? asList(gd.reasons) : "";
  },
};

/** Durable run_events → the RunTranscript item shape, so the engine-detail drawer
 *  can replay a settled run from the same renderer the live stream feeds. */
export function transcriptItemsFromEvents(events: TranscriptEvent[]): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  let seq = 0;
  const push = (item: Omit<TranscriptItem, "seq" | "ts">, ts: number) =>
    items.push({ ...item, seq: (seq += 1), ts });
  for (const e of events) {
    const data = e.data ?? {};
    if (e.type === "activity") {
      push(
        {
          kind: "activity",
          node: String(data.node ?? e.node ?? ""),
          activity: {
            kind: String(data.kind ?? ""),
            detail: data.detail == null ? undefined : String(data.detail),
            result: data.result == null ? undefined : String(data.result),
            node: String(data.node ?? e.node ?? ""),
          },
        },
        e.ts,
      );
    } else if (e.type === "thought") {
      const text = String(data.text ?? "");
      if (text) push({ kind: "thought", node: String(data.node ?? e.node ?? ""), text }, e.ts);
    } else if (e.type === "update") {
      const node = String(data.node ?? e.node ?? "");
      push({ kind: "phase", node }, e.ts);
      const update = data.update;
      if (update && typeof update === "object") {
        const body = NODE_TEXT[node]?.(update as Record<string, unknown>) ?? "";
        if (body.trim()) push({ kind: "body", node, body }, e.ts);
      }
    } else if (e.type === "interrupt") {
      push({ kind: "gate", node: "gate" }, e.ts);
    }
  }
  return items;
}

export interface HonestyBadge {
  kind: HonestyKind;
  /** Unverified material-claim count (meaningful for kind "unverified"). */
  count: number;
}

/** The header verdict — strictly honest SEMANTICS (words live in plain.ts):
 *  "clean" ONLY for a delivery where every material claim evaluated satisfied —
 *  unevaluable/unbound never count as verified. */
export function honestyBadge(rows: LedgerRow[]): HonestyBadge {
  const delivered = rows.some((r) => r.kind === "delivered");
  const terminated = rows.find((r) => r.kind === "terminated");
  const decomposition = rows.find((r) => r.kind === "decomposition");
  const material =
    decomposition?.kind === "decomposition"
      ? decomposition.claims.filter((c) => c.material)
      : [];
  if (delivered) {
    if (material.length === 0) return { kind: "no-claims", count: 0 };
    const unverified = material.filter((c) => c.verdict !== "satisfied").length;
    return unverified === 0
      ? { kind: "clean", count: 0 }
      : { kind: "unverified", count: unverified };
  }
  if (terminated?.kind === "terminated") return { kind: "nothing", count: 0 };
  return { kind: "in-progress", count: 0 };
}

/* --------------------------------------------------------------- checksum */

/** Recompute the run's integrity checksum in the browser — the exact recipe the
 *  engine sealed with (mosaera_core.persist.make_receipt_id):
 *  sha256(runId \n commitSha \n engineVersion \n receiptPayload), hex.
 *  Null when the inputs were never stamped, or outside a secure context. */
export async function computeReceiptChecksum(row: {
  runId: string;
  commitSha: string;
  engineVersion: string | null;
  receiptPayload: string | null;
}): Promise<string | null> {
  if (row.receiptPayload == null || row.engineVersion == null) return null;
  if (typeof crypto === "undefined" || !crypto.subtle) return null;
  const material = `${row.runId}\n${row.commitSha}\n${row.engineVersion}\n${row.receiptPayload}`;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(material));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
