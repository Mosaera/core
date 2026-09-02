/* The work panel (#63): ONE panel showing only the selected agent's work.

   Two compositions:
   - default (drawer / legacy): header + a two-column grid of blocks.
   - stage (theater v2.3): a FIXED-HEIGHT exclusive accordion — one section open at a
     time (FAQ-style), the open body scrolls, so toggling sections never resizes the
     page. Identity lives on the PortraitCard beside it. */

import { useEffect, useState } from "react";

import { AgentAvatar } from "@/components/AgentAvatar";
import { cn } from "@/lib/utils";

import type { AgentState } from "../../../lib/engine";
import type { WorkModel } from "../../../lib/engineWork";
import { RunReportSection } from "../evidence";
import { Block, CotSteps, EmptyBlock, ProseBlock, TaskBlock, TerminalBlock, TestResultsPanel } from "./blocks";

const STATUS_CHIP: Record<AgentState["status"], { text: string; cls: string }> = {
  done: { text: "done", cls: "bg-success/10 text-success" },
  current: { text: "working now", cls: "bg-primary/10 text-primary" },
  dead: { text: "stopped", cls: "bg-destructive/10 text-destructive" },
  pending: { text: "not started", cls: "bg-muted text-muted-foreground" },
  disabled: { text: "disabled", cls: "bg-muted/50 text-muted-foreground/70" },
};

type Section = WorkModel["sections"][number];

function sectionTitle(s: Section): string {
  switch (s.kind) {
    case "empty":
      return "Nothing yet";
    case "report":
      return s.title;
    default:
      return s.title;
  }
}

function sectionCount(s: Section): number | null {
  if (s.kind === "cot") return s.items.length;
  if (s.kind === "tools") return s.items.reduce((n, t) => n + (t.count ?? 1), 0);
  if (s.kind === "tests") return s.rows.length;
  return null;
}

function SectionBody({ s, stage, paused = false }: { s: Section; stage: boolean; paused?: boolean }) {
  switch (s.kind) {
    case "prose":
      return <ProseBlock text={s.text} roomy={stage} />;
    case "cot":
      return <CotSteps items={s.items} collapsible={!stage && s.live !== undefined} paused={paused} />;
    case "terminal":
      return <TerminalBlock text={s.text} />;
    case "tests":
      return <TestResultsPanel rows={s.rows} />;
    case "tools":
      return <TaskBlock items={s.items} />;
    case "report":
      return <RunReportSection rid={s.runId} />;
    case "empty":
      return <EmptyBlock reason={s.reason} />;
  }
}

export function WorkPanel({
  work,
  agent,
  stage = false,
  paused = false,
  passCount = 1,
  passIdx = 0,
  onPass,
}: {
  work: WorkModel;
  agent: AgentState;
  stage?: boolean;
  /** An interrupt is open — the thought stream prints complete instead of typing. */
  paused?: boolean;
  /** >1 when the agent worked multiple passes (Build → checks → Build). */
  passCount?: number;
  passIdx?: number;
  onPass?: (i: number) => void;
}) {
  const chip = STATUS_CHIP[agent.status];

  // ----- stage: fixed-height exclusive accordion -----
  const sections = work.sections;
  const liveCotIdx = sections.findIndex((s) => s.kind === "cot" && s.live);
  const defaultOpen = liveCotIdx >= 0 ? liveCotIdx : sections.length > 0 ? 0 : -1;
  const [open, setOpen] = useState(defaultOpen);
  // Follow the agent switch / the live thought stream appearing.
  useEffect(() => setOpen(defaultOpen), [work.agent, defaultOpen]);

  if (stage) {
    if (sections.length === 1 && sections[0].kind === "empty") {
      return (
        <section
          aria-label={`${work.name}'s work`}
          data-work-agent={work.agent}
          className="flex h-full flex-col justify-center"
        >
          <EmptyBlock reason={sections[0].reason} />
        </section>
      );
    }
    return (
      <section
        aria-label={`${work.name}'s work`}
        data-work-agent={work.agent}
        className="flex h-full min-h-0 flex-col gap-1.5"
      >
        {/* The executive summary lives FREE above the accordion — always visible,
            filling the quiet space when everything below is folded. */}
        {(work.summary || passCount > 1) && (
          <div className="mb-2 flex shrink-0 items-start justify-between gap-4 px-1">
            {work.summary && (
              <p className="text-[15px] leading-relaxed text-foreground/85">{work.summary}</p>
            )}
            {passCount > 1 && onPass && (
              <span className="ml-auto flex shrink-0 items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
                <button
                  type="button"
                  aria-label="Previous pass"
                  disabled={passIdx === 0}
                  onClick={() => onPass(Math.max(0, passIdx - 1))}
                  className="cursor-pointer rounded border border-white/10 bg-white/4 px-1.5 py-0.5 hover:bg-white/10 disabled:cursor-default disabled:opacity-40"
                >
                  ‹
                </button>
                pass {passIdx + 1}/{passCount}
                <button
                  type="button"
                  aria-label="Next pass"
                  disabled={passIdx >= passCount - 1}
                  onClick={() => onPass(Math.min(passCount - 1, passIdx + 1))}
                  className="cursor-pointer rounded border border-white/10 bg-white/4 px-1.5 py-0.5 hover:bg-white/10 disabled:cursor-default disabled:opacity-40"
                >
                  ›
                </button>
              </span>
            )}
          </div>
        )}
        {sections.map((s, i) => {
          const count = sectionCount(s);
          const isOpen = i === open;
          return (
            <div key={i} className={cn("flex flex-col", isOpen && "min-h-0 flex-1")}>
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? -1 : i)}
                className={cn(
                  "flex shrink-0 cursor-pointer items-center gap-2 rounded-md border-0 px-3 py-2 text-left transition-colors",
                  isOpen ? "bg-white/8" : "bg-muted/30 hover:bg-muted/50",
                )}
              >
                <span className="font-mono text-[11.5px] uppercase tracking-[0.14em] text-foreground/90">
                  {sectionTitle(s)}
                </span>
                {count != null && (
                  <span className="font-mono text-[10.5px] tabular-nums text-muted-foreground/70">
                    {count}
                  </span>
                )}
                <span
                  className={cn(
                    "ml-auto shrink-0 font-mono text-[10px] text-muted-foreground/60 transition-transform",
                    isOpen && "rotate-180",
                  )}
                >
                  ▾
                </span>
              </button>
              {isOpen && (
                <div className="min-h-0 flex-1 overflow-y-auto px-1 py-3 text-[15px] leading-relaxed [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
                  <SectionBody s={s} stage paused={paused} />
                </div>
              )}
            </div>
          );
        })}
      </section>
    );
  }

  // ----- default: the drawer/legacy grid -----
  return (
    <section
      aria-label={`${work.name}'s work`}
      data-work-agent={work.agent}
      className="flex flex-col items-stretch gap-5 px-1 py-6"
    >
      <header className="mb-4 flex items-center gap-3">
        {work.agent === "you" ? (
          <span className="flex size-[34px] items-center justify-center rounded-full border border-border bg-muted font-mono text-[9px] font-semibold text-primary">
            YOU
          </span>
        ) : (
          <AgentAvatar actor={work.name} size={34} />
        )}
        <h3 className="text-[15.5px] font-semibold">{work.name}</h3>
        <span className="text-[12.5px] text-muted-foreground">{work.role}</span>
        <span
          className={cn(
            "ml-auto rounded-full px-2.5 py-[3px] font-mono text-[10px] font-semibold tracking-[0.06em]",
            chip.cls,
          )}
        >
          {chip.text}
        </span>
      </header>

      {sections.length === 1 && sections[0].kind === "empty" ? (
        <EmptyBlock reason={sections[0].reason} />
      ) : (
        <div className="grid gap-x-8 gap-y-7 sm:grid-cols-2">
          {sections.map((s, i) => {
            if (s.kind === "empty") return <EmptyBlock key={i} reason={s.reason} />;
            const badges =
              s.kind === "cot" && s.live
                ? [{ text: "thinking", tone: "live" as const }]
                : s.kind === "tests"
                  ? [
                      { text: `${s.passed} green`, tone: "ok" as const },
                      { text: `${s.failed} failed`, tone: s.failed > 0 ? ("bad" as const) : ("dim" as const) },
                    ]
                  : undefined;
            const wide = s.kind === "terminal" || s.kind === "report" || (s.kind === "cot" && s.live);
            return (
              <Block key={i} title={sectionTitle(s)} wide={wide} badges={badges}>
                <SectionBody s={s} stage={false} />
              </Block>
            );
          })}
        </div>
      )}
    </section>
  );
}
