/* The work-panel primitives (#63): plan/chain-of-thought steps, terminal output,
   check-run results and tool-call blocks. Hand-rolled in the shadcn/ai idiom —
   no new dependencies. Presentational only: every honesty decision was already
   made in engineWork.ts, these just render it.

   Flat by design (matching SettingsSection): a label and its content in open
   space, never a floating card — the page reads as one console surface. */

import { BrainCircuit, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import type { CotItem, TestRow, ToolItem } from "../../../lib/engineWork";
import { PmMarkdown } from "../../pm/PmMarkdown";

/** One labelled region: a mono eyebrow, optional right-aligned badges, content. */
export function Block({
  title,
  badges,
  wide,
  children,
}: {
  title: string;
  badges?: { text: string; tone: "ok" | "bad" | "dim" | "live" }[];
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("flex min-w-0 flex-col items-stretch gap-2", wide && "sm:col-span-2")}>
      <header className="flex items-center gap-2 border-b border-border/60 pb-1.5">
        <h4 className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          {title}
        </h4>
        {badges && badges.length > 0 && (
          <span className="ml-auto flex gap-1.5">
            {badges.map((b) => (
              <span
                key={b.text}
                className={cn(
                  "font-mono text-[10px] font-semibold",
                  b.tone === "ok" && "text-success",
                  b.tone === "bad" && "text-destructive",
                  b.tone === "dim" && "text-muted-foreground",
                  b.tone === "live" && "animate-pulse text-primary",
                )}
              >
                {b.text}
              </span>
            ))}
          </span>
        )}
      </header>
      {children}
    </section>
  );
}

/** The model narrates in markdown; a reasoning step renders it as prose. */
function plainThought(text: string): string {
  return text
    .replace(/^#{1,4}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/(^|\s)\*([^*\n]+)\*(?=\s|$)/g, "$1$2");
}

/** Progressive reveal of a newly-arrived reasoning turn (the Claude-style stream feel).
 *  Real text, paced at reading speed — the durable record is never ahead of this by more
 *  than a moment, and a re-render with the same text never restarts. */
/** Reveal progress survives unmount (agent switches must not re-type seen text). */
const REVEALED = new Map<string, number>();

function TypewriterText({ text }: { text: string }) {
  const [shown, setShown] = useState(() => REVEALED.get(text) ?? 0);
  const last = useRef(text);
  useEffect(() => {
    if (last.current !== text) {
      last.current = text;
      setShown(REVEALED.get(text) ?? 0);
    }
    if (shown >= text.length) return;
    const id = setInterval(
      () =>
        setShown((n) => {
          const next = Math.min(n + 2, text.length);
          if (REVEALED.size > 300) REVEALED.clear();
          REVEALED.set(text, next);
          return next;
        }),
      30,
    );
    return () => clearInterval(id);
  }, [text, shown]);
  return (
    <span className="whitespace-pre-wrap">
      {text.slice(0, shown)}
      {shown < text.length && <span className="animate-pulse text-primary">▍</span>}
    </span>
  );
}

function firstLine(text: string): string {
  return text.split("\n").find((l) => l.trim()) ?? "";
}

/** Stepped reasoning, shadcn.io/ai chain-of-thought style: done steps ticked, the live
 *  one pulsing, a connector rail — the NEWEST step types itself out at reading speed.
 *  `collapsible` (the live thought stream) folds to ONE summary line — latest thought +
 *  a flashing activity dot — with the full reasoning behind the disclosure. */
export function CotSteps({
  items,
  collapsible,
  paused = false,
}: {
  items: CotItem[];
  collapsible?: boolean;
  /** An interrupt is open: nothing is thinking — print the tail complete, no typing. */
  paused?: boolean;
}) {
  if (collapsible) {
    const latest = items[items.length - 1];
    const active = items.some((i) => i.state === "active");
    return (
      // Open while the agent is thinking (the live typing is the show); once the last
      // turn settles it folds to the summary line, chevron to reopen.
      <details className="group" open={active || undefined}>
        <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md bg-muted/30 px-2.5 py-2 hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
          <BrainCircuit className={cn("size-3.5 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">
            {latest ? firstLine(plainThought(latest.text)) : "—"}
          </span>
          {active && <span aria-hidden className="animate-pulse text-primary">●</span>}
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground/60">
            {items.length}
          </span>
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        <div className="mt-2 pl-1">
          <CotList items={items} paused={paused} />
        </div>
      </details>
    );
  }
  return <CotList items={items} paused={paused} />;
}

function CotList({ items, paused = false }: { items: CotItem[]; paused?: boolean }) {
  return (
    <ol className="flex flex-col items-stretch">
      {items.map((it, i) => (
        <li key={i} className="relative flex gap-3 py-1.5">
          {i < items.length - 1 && (
            <span aria-hidden className="absolute left-2 top-6 h-[calc(100%-14px)] w-px bg-border" />
          )}
          <span
            aria-hidden
            data-step={it.state}
            className={cn(
              "z-[1] mt-0.5 flex size-[17px] shrink-0 items-center justify-center rounded-full text-[9.5px] font-extrabold",
              it.state === "active"
                ? "animate-pulse bg-primary/20 text-primary"
                : "bg-success/15 text-success",
            )}
          >
            {it.state === "active" ? "●" : "✓"}
          </span>
          <span className="min-w-0 text-[inherit] leading-relaxed">
            {it.state === "active" && !paused ? (
              <TypewriterText text={plainThought(it.text)} />
            ) : (
              <span className="whitespace-pre-wrap">{plainThought(it.text)}</span>
            )}
            {it.sub && <span className="mt-0.5 block text-[11.5px] text-muted-foreground">{it.sub}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Command output. The only tinted surface we keep — unreadable without one. */
export function TerminalBlock({ text }: { text: string }) {
  return (
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-foreground/[0.03] px-3 py-2 font-mono text-[11.5px] leading-relaxed text-muted-foreground">
      {text}
    </pre>
  );
}

/** Check runs: a pass/fail glyph per run, its label and honest sub-line. */
export function TestResultsPanel({ rows }: { rows: TestRow[] }) {
  return (
    <ul className="flex flex-col items-stretch">
      {rows.map((r, i) => (
        <li
          key={i}
          className={cn(
            "flex items-baseline gap-2.5 py-1.5 text-[12.5px]",
            i > 0 && "border-t border-border/40",
          )}
        >
          <span
            aria-hidden
            className={cn("font-extrabold", r.passed ? "text-success" : "text-destructive")}
          >
            {r.passed ? "✓" : "✗"}
          </span>
          <span className="font-medium">{r.label}</span>
          {r.sub && <span className="ml-auto text-[11px] text-muted-foreground">{r.sub}</span>}
        </li>
      ))}
    </ul>
  );
}

/** Tool calls / decisions: left-accent activity-log rows. Unsettled = running.
 *  A folded run of same-kind calls ("read ×7") opens to its individual calls. */
export function TaskBlock({ items }: { items: ToolItem[] }) {
  return (
    <ul className="flex flex-col items-stretch gap-1.5">
      {items.map((t, i) => {
        const grouped = (t.count ?? 1) > 1 && t.entries;
        const head = (
          <span className="min-w-0 flex-1">
            <span
              className={cn(
                "block font-mono text-[11px] font-semibold",
                t.settled ? "text-success" : "text-primary",
              )}
            >
              {t.title}
            </span>
            {t.detail && (
              <span className="mt-0.5 block truncate text-[11.5px] text-muted-foreground">
                {t.detail}
              </span>
            )}
          </span>
        );
        return (
          <li
            key={i}
            data-settled={t.settled}
            className={cn(
              "border-l-2 py-1 pl-3",
              t.settled ? "border-success/40" : "border-primary/50",
            )}
          >
            {grouped ? (
              <details className="group/tool">
                <summary className="flex cursor-pointer list-none items-center gap-1.5 [&::-webkit-details-marker]:hidden">
                  {head}
                  <span className="shrink-0 font-mono text-[10px] text-muted-foreground/60 transition-transform group-open/tool:rotate-180">
                    ▾
                  </span>
                </summary>
                <ul className="mt-1 flex flex-col gap-1 border-l border-border/50 pl-2.5">
                  {t.entries!.map((e, j) => (
                    <li key={j} className="min-w-0">
                      <span
                        className="block truncate font-mono text-[11px] text-foreground/80"
                        title={e.title}
                      >
                        {e.title}
                      </span>
                      {e.detail && (
                        <span
                          className="block truncate text-[11px] text-muted-foreground"
                          title={e.detail}
                        >
                          {e.detail}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            ) : (
              head
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function ProseBlock({ text, roomy = false }: { text: string; roomy?: boolean }) {
  // Agents narrate in markdown; render it instead of showing literal ** and ## noise.
  // `roomy` (the stage accordion) lets the section's own scroll area size it.
  return (
    <div
      className={cn(
        "leading-relaxed [&_p]:mb-2 [&_h2]:mb-1.5 [&_h2]:text-[13px] [&_h2]:font-semibold [&_h3]:mb-1 [&_h3]:font-semibold [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_code]:font-mono [&_code]:text-[11.5px]",
        roomy ? "text-[inherit]" : "max-h-72 overflow-auto text-[12.5px]",
      )}
    >
      <PmMarkdown>{text}</PmMarkdown>
    </div>
  );
}

/** The honest empty state: why there is nothing to show for this agent. */
export function EmptyBlock({ reason }: { reason: string }) {
  return <p className="max-w-2xl py-1 text-[12.5px] text-muted-foreground">{reason}</p>;
}
