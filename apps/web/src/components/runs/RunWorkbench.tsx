import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

import { api, type BacklogItem } from "../../api/client";
import { TotalElapsed } from "./TotalElapsed";
import { useRunStream } from "../../hooks/useRunStream";
import { deriveLedger } from "../../lib/ledger";
import { priorAttemptShapes } from "../../lib/radar";
import { DURABLE_STATUS, parseReceipt } from "../../lib/runs";
import { EngineView } from "./engine/EngineView";
import { CapabilityLimitNote, WithheldAskNote } from "./evidence";
import { deriveHeroVariant } from "./hero/heroState";
import { BudgetGate } from "./BudgetGate";
import { livePauseCause, stopReason } from "../../lib/plain";
import { ConsoleLabel } from "../overview/bits";
import { GatePanel } from "./GatePanel";
import { RunHero, StorySoFarRule } from "./hero/RunHero";
import { RecordFooter } from "./RecordFooter";

/** The Live Workbench: one page for a run's whole life — what the agents are
 *  doing (milestones), the gate when it parks, the evidence they produced, and
 *  the run's facts. Correctness is poll-authoritative (useRunStream); the SSE
 *  activity feed enriches it. */
export function RunWorkbench({ rid, projectId }: { rid: string; projectId?: string }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const stream = useRunStream(rid);
  const [busy, setBusy] = useState(false);
  // One deliberate opt-in spares N identical clicks on the Proctor's tests/ writes;
  // the server-side tests/ scope (ADR-0013) is untouched — this only clicks Allow.
  const [autoAllowTests, setAutoAllowTests] = useState(false);
  // ADR-0101 dock: a gate ARRIVES as a slim pinned bar (no page reflow); expanding
  // opens the full panel inside the dock. Collapses again per new gate.
  const [dockOpen, setDockOpen] = useState(false);
  // D3 (#116): the id of the gate that was OPEN when a mode switch reached only "the next
  // gate" (writes_auto() is consulted BEFORE a gate parks, so the switch can't reach back into
  // one already open). Compared against the CURRENT gate's id below rather than cleared by a
  // separate effect: an id comparison can't race a click the way an effect keyed on the same id
  // can (an effect queued by the gate's OWN arrival can still be pending when the switch fires,
  // and then runs afterwards and wipes it — observed in-repo). Once this gate resolves and a
  // different one (or none) appears, the ids stop matching and the hint disappears on its own.
  const [pendingModeGateId, setPendingModeGateId] = useState<string | null>(null);

  // `missing` = no live session (404): a durable-only run — after an API restart
  // evicts a finished session, or a row written straight to history. Treat it as
  // terminal so the durable record below becomes the page, instead of the old
  // behavior: polling "Running" forever over a run that isn't.
  const terminal =
    stream.final != null ||
    stream.missing ||
    ["completed", "incomplete", "error", "cancelled"].includes(stream.status);

  // Durable record once finished — richer than the live stream.
  const { data: detail, error: detailError } = useQuery({
    queryKey: ["run", rid],
    queryFn: () => api.runDetail(rid),
    // Live too (slow poll): the durable record carries mid-run decisions the stage
    // shows — notably the model-authored agent summaries persisted at each park.
    enabled: true,
    refetchInterval: terminal ? false : 5000,
    retry: 1,
  });
  // The run's events, from the durable record in BOTH modes: run_events is written
  // as each event is emitted, so the engine view survives a refresh mid-run instead
  // of restarting from an empty in-memory feed. Polled while the run is live.
  const { data: transcriptData } = useQuery({
    queryKey: ["run-transcript", rid],
    queryFn: () => api.transcript(rid),
    refetchInterval: terminal ? false : 2000,
    retry: 1,
  });
  const { data: itemProject } = useQuery({
    queryKey: ["project", detail?.project_id],
    queryFn: () => api.getProject(detail!.project_id!),
    enabled: Boolean(detail?.project_id && detail?.item_id != null),
  });
  const item: BacklogItem | undefined = (itemProject?.backlog ?? []).find(
    (i) => i.id === detail?.item_id,
  );

  async function decide(
    approve: boolean,
    feedback: string,
    authorizeTests: string[] = [],
    optionId?: string,
  ) {
    setBusy(true);
    queryClient.setQueryData(["run-snapshot", rid], (old: unknown) =>
      old && typeof old === "object"
        ? { ...(old as Record<string, unknown>), pending_interrupt: null, status: "running" }
        : old,
    );
    try {
      await api.approve(rid, approve, feedback, authorizeTests, optionId);
      stream.resync();
      void queryClient.invalidateQueries({ queryKey: ["run", rid] });
    } catch (e) {
      // The optimistic "gate resolved" was wrong — pull server truth back so the gate reappears.
      void queryClient.invalidateQueries({ queryKey: ["run-snapshot", rid] });
      toast({
        title: approve ? "Couldn't approve the run" : "Couldn't submit your decision",
        description: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    try {
      await api.cancelRun(rid);
      stream.resync();
    } catch (e) {
      toast({
        title: "Couldn't cancel the run",
        description: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    }
  }

  // The moment the run seals, pull the durable record — the verdict band needs the
  // receipt, and a mid-run cached detail (5s poll) may predate finalize.
  useEffect(() => {
    if (terminal) void queryClient.invalidateQueries({ queryKey: ["run", rid] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [terminal]);

  const gate = stream.gate?.value;
  const gateId = stream.gate?.id;
  useEffect(() => setDockOpen(false), [gateId]);
  // D3: switchMode below is redefined every render and closes over THIS render's gateId — the
  // classic stale-closure trap, since a click starts the request against whatever gateId was
  // current at click time, and by the time the response lands a newer render (and closure) may
  // exist. A ref always reads the latest value, so the response is matched against the gate that
  // was actually open when it was answered, not a value frozen when the click fired.
  const gateIdRef = useRef(gateId);
  gateIdRef.current = gateId;
  const liveMode = stream.interactionMode ?? "ask";
  // #108. Derived, never stored: the cause the engine recorded at THIS pause, in the same plain
  // words the settled-run card uses. `parkCause` degrades readably on an unknown token (the backend
  // vocabulary has grown before), and a diagnosis with nothing to say yields null so the panel
  // stays silent rather than inventing a reason.
  const pausedDiagnosis = detail?.diagnosis ?? null;
  const parkedBecause = (() => {
    if (!pausedDiagnosis) return null;
    const sentence = livePauseCause(pausedDiagnosis.park_cause ?? "");
    const channel = stopReason(pausedDiagnosis);
    if (!sentence && !channel) return null;
    return {
      sentence: sentence || channel?.text || "",
      label: channel?.label ?? "",
      detail: sentence && channel ? channel.text : "",
    };
  })();
  async function switchMode(mode: string) {
    try {
      const result = await api.setRunMode(rid, mode);
      setPendingModeGateId(result.currently_parked ? (gateIdRef.current ?? null) : null);
      stream.resync();
    } catch (e) {
      toast({
        title: "Couldn't switch the mode",
        description: e instanceof Error ? e.message : String(e),
        variant: "error",
      });
    }
  }
  useEffect(() => {
    if (!autoAllowTests || busy || !gate) return;
    const isWrite = gate.action === "write_file" || gate.action === "edit_file";
    if (isWrite && (gate.path ?? "").startsWith("tests/")) {
      void decide(true, "auto-allowed: test-file write (operator opt-in this run)");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoAllowTests, gateId]);
  const ledgerRows = deriveLedger({
    detail,
    item,
    events: transcriptData?.events,
    live: terminal
      ? undefined
      : { gate: gate ?? null, status: stream.status, startedAt: stream.startedAt },
  });
  // A durable-only run reports its status from the record, in the live vocabulary.
  const status = stream.missing
    ? detail
      ? (DURABLE_STATUS[detail.status] ?? detail.status.toLowerCase())
      : "unknown"
    : stream.status;

  if (stream.missing && detailError) {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        <RunHero
          rid={rid}
          projectId={projectId}
          task="Run not found"
          variant={{ kind: "terminated", status: "NOT FOUND", reason: "", reasonIsFull: false }}
          rows={[]}
        />
        <p className="max-w-2xl text-sm text-muted-foreground">
          This run isn&apos;t active and no record of it exists.
        </p>
      </div>
    );
  }

  const sealRow = (ledgerRows.find((r) => r.kind === "seal") ?? null) as
    | Extract<(typeof ledgerRows)[number], { kind: "seal" }>
    | null;
  const variant = deriveHeroVariant({
    status,
    gate: terminal ? null : (gate ?? null),
    rows: ledgerRows,
    phase: stream.phase,
    startedAt: stream.startedAt,
    terminationReason: stream.terminationReason ?? detail?.termination_reason ?? null,
    diagnosis: detail?.diagnosis ?? null,
  });

  return (
    <div className="flex min-w-0 flex-col gap-5">
      {/* The page IS whatever the run is right now: the verdict, the decision,
          live progress, or an honest ending. */}
      <RunHero
        rid={rid}
        projectId={projectId}
        task={detail?.task}
        variant={variant}
        rows={ledgerRows}
        mode={stream.mode}
        revisions={detail?.iterations}
        busy={busy}
        onDecide={undefined}
        autoAllowTests={autoAllowTests}
        onAutoAllowTests={setAutoAllowTests}
        onCancel={terminal ? undefined : cancel}
        mergeHref={
          detail?.project_id ? `/projects/${detail.project_id}/delivery?view=changes` : undefined
        }
      />

      {/* An honest reason the run couldn't finish (no-progress breaker or a hard
          budget stop) — surfaced live the moment the run finalizes, not just in history. */}
      {terminal && <CapabilityLimitNote detail={detail} />}
      {terminal && <WithheldAskNote detail={detail} />}

      {variant.kind === "needs-you" && <StorySoFarRule />}

      {/* ADR-0101: the live interaction mode, switchable mid-run. */}
      {!terminal && (
        <div className="flex items-center justify-end gap-1.5">
          <TotalElapsed startedAt={stream.startedAt} paused={gate != null} />
          <span className="ml-3 font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
            mode
          </span>
          {(["ask", "accept", "auto"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={liveMode === m}
              onClick={() => switchMode(m)}
              title={
                m === "ask"
                  ? "Every write asks you first"
                  : m === "accept"
                    ? "Writes auto-accepted (each recorded); direction, escalation and delivery still ask"
                    : "Only escalation, stuck and delivery gates ask"
              }
              className={cn(
                "cursor-pointer rounded-full border px-3 py-1 font-mono text-[11.5px] leading-none transition-colors",
                liveMode === m
                  ? "border-primary/50 bg-primary/15 text-primary"
                  : "border-white/10 bg-white/4 text-muted-foreground hover:bg-white/10 hover:text-foreground",
              )}
            >
              {m}
            </button>
          ))}
        </div>
      )}
      {/* D3 (#116): the switch above already took hold (the toggle itself moved) — this says
          the honest scope of that: it governs the run's NEXT gate. A gate already open (the
          dock below) parked under the mode in force when IT raised, and stays that way. */}
      {!terminal && gate != null && gateId != null && pendingModeGateId === gateId && (
        <p className="flex items-center justify-end font-mono text-[10.5px] text-muted-foreground">
          mode applies from the next gate — this one is already waiting on you below
        </p>
      )}

      {/* The engine: the agent team drawn from this run's own events, the
          timeline, the selected agent's work, and — once it concludes — why it
          delivered or why it stopped, closing with the RECORD seal. */}
      <EngineView
        events={
          // Zero-latency while live and healthy (SSE replays full history on subscribe);
          // the polled durable record carries refreshes, drops, and every finished run.
          !terminal && stream.connected && stream.liveEvents.length > 0
            ? stream.liveEvents
            : transcriptData?.events
        }
        detail={detail}
        rows={ledgerRows}
        live={
          terminal
            ? undefined
            : {
                status: stream.status,
                phase: stream.phase,
                // Only a real PARK (delivery/budget) hands the stage to Justice; a
                // mid-run write approval keeps it with the asking agent.
                gateOpen: gate != null && !/file/.test(gate.action ?? ""),
              }
        }
        controls={stream.controls}
        interruptOpen={!terminal && gate != null}
        receipt={parseReceipt(detail)}
        ghosts={detail ? priorAttemptShapes(itemProject?.runs ?? [], detail) : []}
        footer={
          <RecordFooter
            rid={rid}
            seal={sealRow}
            detail={detail}
            cost={stream.cost}
            budget={stream.budget}
            profiles={stream.profiles}
          />
        }
      />

      {/* The gate dock (ADR-0101): the run stops and ASKS — a slim pinned bar,
          zero reflow; Review expands the full evidence panel inside the dock. */}
      {!terminal && gate && (
        <div
          className="fixed bottom-0 right-0 z-40 animate-in fade-in slide-in-from-bottom-4 border-t-2 border-primary/60 bg-black/80 shadow-[0_-16px_50px_rgba(0,0,0,0.5)] backdrop-blur-md duration-300"
          style={{ left: "var(--sidebar-width, 0px)" }}
        >
          <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-3.5">
            <span className="animate-pulse rounded-full bg-primary/15 px-2.5 py-1 font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em] text-primary">
              needs you
            </span>
            <span className="min-w-0 flex-1 truncate text-[14px]">
              The run is paused —{" "}
              <span className="font-mono text-primary">{gate.action ?? "your decision"}</span>
              {gate.path ? <span className="text-muted-foreground"> · {gate.path}</span> : null}
            </span>
            <button
              type="button"
              onClick={() => setDockOpen((v) => !v)}
              className="shrink-0 cursor-pointer rounded-md bg-primary px-4 py-2 font-mono text-[12.5px] font-semibold text-primary-foreground transition-colors hover:bg-primary/85"
            >
              {dockOpen ? "Hide" : "Review"}
            </button>
          </div>
          {dockOpen && (
            <div className="mx-auto max-h-[70vh] max-w-5xl overflow-y-auto px-6 pb-4 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
              {/* Route by action, exactly as DecisionHero does. The dock used to render
                  GatePanel unconditionally, and GatePanel has no budget branch — so a budget
                  park fell through to the legacy "Approve & deliver" / "Send back" buttons while
                  the hero above it showed the honest "Continue — raise limit" / "Stop run".
                  Same paused run, two different stories, and the dock's were both wrong: approve
                  grants another budget's worth (runner/_budget.py), and "Send back" TERMINALLY
                  CANCELS. F61's class, found by audit 2026-08-21. */}
              {/* #108: WHY the run is asking, above what the gate could not find. The engine
                  records a cause at the pause (`_record_pause_diagnosis`), and until this was
                  rendered the operator read only a list of absences — "no checks were attempted",
                  "the reviewer's verdict couldn't be read" — none of which name a cause or suggest
                  a move. Confirmed live 2026-08-23 on an `under_specified` park: the reason existed
                  in the record and reading the API was the only way to reach it.

                  Rendered ONLY from what the record carries: no cause recorded means nothing shown,
                  never a guess. The plain sentences are `plain.ts`'s, already used by the settled-run
                  diagnosis card, so a park says the same thing here as it does afterwards. */}
              {parkedBecause && (
                <div className="mb-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                  <ConsoleLabel>why the run stopped</ConsoleLabel>
                  <p className="mt-1 text-[13px] text-foreground">{parkedBecause.sentence}</p>
                  {parkedBecause.detail && (
                    <p className="mt-1 font-mono text-[11px] leading-relaxed text-muted-foreground">
                      {parkedBecause.label}: {parkedBecause.detail}
                    </p>
                  )}
                </div>
              )}
              {gate.action === "budget" ? (
                <BudgetGate key={gateId} gate={gate} busy={busy} onDecide={decide} variant="hero" />
              ) : (
                <GatePanel
                  key={gateId}
                  gate={gate}
                  busy={busy}
                  onDecide={decide}
                  variant="hero"
                  autoAllowTests={autoAllowTests}
                  onAutoAllowTests={setAutoAllowTests}
                />
              )}
            </div>
          )}
        </div>
      )}

      {stream.error && (
        <p className="rounded-md bg-destructive/10 p-3 font-mono text-xs text-destructive">
          {stream.error}
        </p>
      )}
    </div>
  );
}


