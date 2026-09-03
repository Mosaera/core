/* The engine view (#63): the run page's body — the agent band, the timeline
   strip, the selected agent's work, and (once concluded) the verdict band.
   Selection is one piece of state shared by the band and the timeline: clicking
   either selects the same agent, and the panel below shows only that agent.

   The run's events come from ONE source in both modes — the durable transcript
   (run_events is written as each event is emitted), so a live page survives a
   refresh instead of starting from an empty in-memory feed. */

import { useEffect, useState } from "react";

import type { RunDetail, TranscriptEvent } from "../../../api/client";
import {
  agentSpan,
  defaultSelection,
  deriveAgents,
  type AgentId,
  type EngineInputs,
} from "../../../lib/engine";
import { agentPasses, deriveWork } from "../../../lib/engineWork";
import { honestyBadge, type LedgerRow } from "../../../lib/ledger";
import type { ParsedReceipt } from "../../../lib/runs";
import { PortraitCard } from "./PortraitCard";
import { StepsRail } from "./StepsRail";
import { VerdictBand } from "./VerdictBand";
import { WorkPanel } from "./WorkPanel";

export function EngineView({
  ghosts,
  events = [],
  detail,
  rows,
  live,
  controls,
  interruptOpen = false,
  receipt,
  footer,
}: {
  ghosts?: import("../../../lib/radar").AxisValue[][];
  events?: TranscriptEvent[];
  detail?: RunDetail;
  rows: LedgerRow[];
  /** Live signals; undefined = a sealed run (static band, no traveling dot). */
  live?: EngineInputs["live"];
  /** The control set the run started with; drives the roster's disabled state. */
  controls?: EngineInputs["controls"];
  /** ANY open interrupt (write gate or park): the stage shows paused, not working. */
  interruptOpen?: boolean;
  receipt?: ParsedReceipt;
  /** The RECORD strip, rendered inside the verdict band once the run concludes. */
  footer?: React.ReactNode;
}) {
  const inputs: EngineInputs = { events, detail, live, controls };
  const agents = deriveAgents(inputs);

  // Follow the work while live; once the run settles, land on the decision record.
  const suggested = defaultSelection(inputs);
  const [picked, setPicked] = useState<AgentId | null>(null);
  const [followed, setFollowed] = useState<AgentId>(suggested);
  // Follow the work by default; a manual pick holds only for the CURRENT stage.
  // The moment the run moves to the next agent the stage snaps back to following —
  // browsing an old panel must not strand the view there (measured live 2026-08-13).
  const isLive = Boolean(live);
  useEffect(() => {
    setFollowed(suggested);
    // LIVE only: a sealed run keeps the operator's pick (async detail loads would
    // otherwise wipe it); a live run resumes following as the work advances.
    if (isLive) setPicked(null);
  }, [suggested, isLive]);
  const roster = new Set(agents.map((a) => a.id));
  const selected = picked && roster.has(picked) ? picked : roster.has(followed) ? followed : agents[0]?.id;
  if (!selected) return null;

  const stageVisible = isLive || picked !== null;
  const agent = agents.find((a) => a.id === selected)!;
  // Repeat visits (Build → checks → Build) page per PASS; default = the latest.
  const passes = agentPasses(inputs, selected);
  const [passPick, setPassPick] = useState<number | null>(null);
  useEffect(() => setPassPick(null), [selected]);
  const passIdx = passPick ?? Math.max(0, passes.length - 1);
  const work = deriveWork(
    selected,
    inputs,
    rows,
    passes.length > 1 ? passes[passIdx] : undefined,
  );

  return (
    <div className="flex flex-col items-stretch">
      {/* Theater v2: the run as a stage — steps rail (also the agent switcher), then the
          selected agent's PORTRAIT beside its work. The node-graph band retired here. */}
      <StepsRail
        agents={agents}
        selected={stageVisible ? selected : null}
        onSelect={(id) => setPicked(isLive || picked !== id ? id : null)}
      />
      {/* Sealed runs lead with the AFTER-ACTION verdict — the stage opens on demand
          from the rail (and the selected chip toggles it closed again). */}
      {stageVisible && (
      <div className="flex flex-col gap-6 py-9 lg:h-[640px] lg:flex-row lg:items-stretch">
        <PortraitCard
          agent={agent}
          interruptOpen={interruptOpen}
          workedSpan={agentSpan(inputs, selected)}
          className="h-[420px] w-full max-w-[420px] shrink-0 lg:h-full"
        />
        <div className="min-w-0 flex-1 lg:h-full lg:min-h-0">
          <WorkPanel
            work={work}
            agent={agent}
            stage
            paused={interruptOpen}
            passCount={passes.length}
            passIdx={passIdx}
            onPass={setPassPick}
          />
        </div>
      </div>
      )}
      {/* The verdict band only exists once the run concludes; while it's live the
          RECORD strip still closes the page on its own. */}
      {honestyBadge(rows).kind === "in-progress" ? (
        footer
      ) : (
        <VerdictBand
          rows={rows}
          receipt={receipt}
          testCount={detail?.test_results?.length ?? 0}
          footer={footer}
          diagnosis={detail?.diagnosis}
          runId={detail?.id}
          task={detail?.task}
          pmProjectId={detail?.project_id}
          ghosts={ghosts}
        />
      )}
    </div>
  );
}
