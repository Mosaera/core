import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, type GatePayload, type RunControls, type RunCost, type RunSnapshot, type TranscriptEvent } from "../api/client";
import { withToken } from "../api/auth";
// The shared per-node body-text extraction — live stream and durable replay
// (transcriptItemsFromEvents) must surface identical text. Value import is safe:
// ledger.ts's import from this module is type-only (erased at runtime).
import { NODE_TEXT } from "../lib/ledger";

export interface TimelineEntry {
  node: string;
  body: string;
}

/** A fine-grained tool milestone from a node's activity (read X → N lines /
 *  wrote Y → N chars) — the anti-black-box signal. `node` names the emitting
 *  graph node (implement → Forge, review → Rook) for correct attribution;
 *  `result` is the tool's short outcome. */
export interface RunActivity {
  kind: string;
  detail?: string;
  result?: string;
  node?: string;
}

/** One ordered line/block in the run transcript — the terminal/chat feed. Built
 *  from the SSE stream in arrival order (seq), so tool activities, node-completion
 *  phases, body text and the gate interleave correctly. */
export type TranscriptKind = "phase" | "activity" | "body" | "gate" | "note" | "thought";
export interface TranscriptItem {
  seq: number;
  ts: number;
  kind: TranscriptKind;
  node?: string; // for actor attribution (the component derives the persona/label)
  activity?: RunActivity; // kind === "activity"
  body?: string; // kind === "body" (a node's surfaced output text)
  text?: string; // kind === "note" (a plain line, e.g. run completed)
}

const _MAX_ACTIVITIES = 200;
const _MAX_TRANSCRIPT = 600;

export interface StreamState {
  status: string;
  phase: string;
  /** Why the run ended without delivering (status "incomplete"); null otherwise. */
  terminationReason: string | null;
  mode?: string;
  interactionMode?: string;
  startedAt: number | null;
  entries: TimelineEntry[];
  activities: RunActivity[];
  /** The ordered terminal/chat transcript (phases + tool activities + bodies). */
  transcript: TranscriptItem[];
  /** The same five durable event types, live off the SSE wire in TranscriptEvent shape —
   *  the engine view's zero-latency feed. The server replays full history to a late
   *  subscriber, so while the session lives this is COMPLETE, not a tail. */
  liveEvents: TranscriptEvent[];
  gate: { id: string; value: GatePayload } | null;
  final: RunSnapshot | null;
  /** The run has NO live session (404): a durable-only run — seeded, or evicted
   *  after an API restart. The workbench must fall back to the durable record. */
  missing: boolean;
  error: string | null;
  /** false while the SSE stream is dropped; the poll keeps the UI correct. */
  connected: boolean;
  /** Live token/cost rollup + per-run spend ceilings (from the snapshot). */
  cost: RunCost | null;
  budget: Record<string, number> | null;
  /** The control set this run started with — drives the honest agent/oracle roster. */
  controls: RunControls | null;
  /** The intent profiles the run started with (ADR-0122); null on older servers/rows. */
  profiles: Record<string, string> | null;
  /** Force an immediate snapshot refetch (call after approve/deny). */
  resync: () => void;
}

const TERMINAL = new Set(["completed", "incomplete", "error", "cancelled"]);

/** The server timestamp (epoch ms) an SSE event carries, if any. */
function tsOf(e: Event): number | undefined {
  try {
    const raw = (e as MessageEvent).data;
    return raw ? (JSON.parse(raw) as { ts?: number }).ts : undefined;
  } catch {
    return undefined;
  }
}

/** Subscribe to a run.
 *
 *  Correctness is poll-authoritative: the run's snapshot (status / phase /
 *  pending gate) comes from `getRun` on an interval, so approving advances the
 *  gate and terminal state appears even if the SSE stream dropped. The SSE
 *  stream is enrichment only — it feeds the live activity timeline and nudges
 *  the poll to reconcile instantly when it's healthy. A native stream
 *  disconnect never freezes the UI; the poll carries it. */
export function useRunStream(runId: string): StreamState {
  const qc = useQueryClient();
  const snapshotKey = ["run-snapshot", runId];

  const { data: snap, error: snapError } = useQuery({
    queryKey: snapshotKey,
    queryFn: () => api.getRun(runId),
    // A 404 is an answer (no live session — durable-only run), not a flake.
    retry: (count, err) => !/\b404\b/.test(String(err)) && count < 2,
    // Stop polling once terminal or errored; otherwise reconcile every 1.5s.
    refetchInterval: (q) =>
      TERMINAL.has(String(q.state.data?.status ?? "")) || q.state.error ? false : 1500,
  });
  const missing = snap == null && snapError != null && /\b404\b/.test(String(snapError));

  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [activities, setActivities] = useState<RunActivity[]>([]);
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [liveEvents, setLiveEvents] = useState<TranscriptEvent[]>([]);
  const [connected, setConnected] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    setEntries([]);
    setActivities([]);
    setTranscript([]);
    setLiveEvents([]);
    setConnected(true);
    setErrorMsg(null);
    seq.current = 0;
    // Append an ordered transcript item. Order is the monotonic seq; the timestamp
    // is the SERVER ts carried by the event (so a replayed history keeps real times),
    // falling back to client receive-time only if absent.
    // Mirror an SSE event into the durable TranscriptEvent shape (same payload the
    // run_events table stores), so the engine view renders live and replayed identically.
    let evSeq = 0;
    const pushEvent = (type: TranscriptEvent["type"], payload: Record<string, unknown>) =>
      setLiveEvents((prev) =>
        [
          ...prev,
          {
            seq: (evSeq += 1),
            type,
            node: typeof payload.node === "string" ? payload.node : null,
            ts: typeof payload.ts === "number" ? payload.ts : Date.now(),
            data: payload,
          },
        ].slice(-_MAX_TRANSCRIPT),
      );
    const push = (item: Omit<TranscriptItem, "seq" | "ts">, ts?: number) =>
      setTranscript((prev) =>
        [...prev, { ...item, seq: (seq.current += 1), ts: ts ?? Date.now() }].slice(
          -_MAX_TRANSCRIPT,
        ),
      );
    const bump = () => void qc.invalidateQueries({ queryKey: ["run-snapshot", runId] });
    // EventSource can't set an Authorization header, so the token rides as a
    // `?token=` query param (the API accepts either — see app.py auth middleware).
    const es = new EventSource(withToken(`/api/runs/${runId}/events`));

    // D4: the browser retries a dropped connection on its own (and resumes past what it already
    // saw via the `id:`/Last-Event-ID cursor the server now honors — see runner/_lifecycle.py).
    // `open` fires on that reconnect too, so this is the only place `connected` should flip back
    // true; without it a transient drop left the indicator stuck on "disconnected" forever even
    // after the stream recovered on its own.
    es.addEventListener("open", () => setConnected(true));

    es.addEventListener("update", (e) => {
      const data = JSON.parse((e as MessageEvent).data) as {
        node: string;
        update: Record<string, unknown>;
        ts?: number;
      };
      const text = NODE_TEXT[data.node]?.(data.update ?? {}) ?? "";
      pushEvent("update", data as unknown as Record<string, unknown>);
      setEntries((prev) => [...prev, { node: data.node, body: text }]);
      // A node produced its output → a completion line in the transcript, plus the
      // body block when there's surfaced text (plan/test/scan/review).
      push({ kind: "phase", node: data.node }, data.ts);
      if (text.trim()) push({ kind: "body", node: data.node, body: text }, data.ts);
      bump(); // reconcile phase/status/gate from the authoritative snapshot
    });

    es.addEventListener("activity", (e) => {
      const a = JSON.parse((e as MessageEvent).data) as RunActivity & { ts?: number };
      if (a && typeof a.kind === "string") {
        pushEvent("activity", a as unknown as Record<string, unknown>);
        setActivities((prev) => [...prev, a].slice(-_MAX_ACTIVITIES));
        push({ kind: "activity", node: a.node, activity: a }, a.ts);
      }
    });

    // An agent's reasoning for one model turn — its thinking, streamed per turn.
    es.addEventListener("thought", (e) => {
      const t = JSON.parse((e as MessageEvent).data) as {
        node?: string;
        text?: string;
        ts?: number;
      };
      if (t.text) {
        pushEvent("thought", t as Record<string, unknown>);
        push({ kind: "thought", node: t.node, text: t.text }, t.ts);
      }
    });

    // Escalations (budget park / reasoning ladder) were emitted and persisted but never
    // rendered live — the one event type the stream dropped on the floor.
    es.addEventListener("escalation", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as Record<string, unknown>;
        pushEvent("escalation", data);
        push({ kind: "note", text: String(data.message ?? data.reason ?? "escalation") }, tsOf(e));
      } catch {
        /* telemetry must never break the view */
      }
    });

    es.addEventListener("interrupt", (e) => {
      try {
        pushEvent("interrupt", JSON.parse((e as MessageEvent).data) as Record<string, unknown>);
      } catch {
        pushEvent("interrupt", {});
      }
      push({ kind: "gate", node: "gate" }, tsOf(e));
      bump();
    });
    es.addEventListener("done", (e) => {
      push({ kind: "note", text: "run finished" }, tsOf(e));
      bump();
      es.close();
    });

    es.addEventListener("error", (e) => {
      const raw = (e as MessageEvent).data;
      if (typeof raw === "string" && raw) {
        // App-level error event carries a message.
        const msg = JSON.parse(raw) as { message: string };
        setErrorMsg(msg.message);
        es.close();
      } else {
        // Native connection drop: do NOT silently no-op — mark disconnected and
        // let the authoritative poll keep the UI correct (the old bug froze here).
        setConnected(false);
        bump();
      }
    });

    return () => es.close();
  }, [runId, qc]);

  const status = errorMsg ? "error" : (snap?.status ?? "running");
  const final = snap && TERMINAL.has(snap.status) ? snap : null;

  return {
    status,
    phase: snap?.phase ?? "",
    terminationReason: snap?.termination_reason ?? null,
    mode: snap?.mode,
    interactionMode: snap?.interaction_mode,
    startedAt: snap?.started_at ?? null,
    entries,
    activities,
    transcript,
    liveEvents,
    gate: snap?.pending_interrupt ?? null,
    final,
    missing,
    error: errorMsg,
    connected,
    cost: snap?.cost ?? null,
    budget: snap?.budget ?? null,
    /** The control set this run started with — drives the honest agent/oracle roster. */
    controls: snap?.controls ?? null,
    profiles: snap?.profiles ?? null,
    resync: () => void qc.invalidateQueries({ queryKey: snapshotKey }),
  };
}
