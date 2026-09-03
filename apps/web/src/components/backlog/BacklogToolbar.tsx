import { MessageSquare, Plus, RefreshCw, Sparkles, Zap } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import type { Project } from "../../api/client";
import { backlogSummary } from "../../lib/backlog";
import { backlogCounts } from "../../lib/overview";

/** Compact control row above the board: identity + honest counts on the left,
 *  actions on the right. No search/filter until they actually work. */
export function BacklogToolbar({
  project,
  onAdd,
  addPending,
  onRefresh,
  onRunAutonomously,
  onToggleAutonomous,
  onAskReprioritize,
  onCurate,
  curatePending,
}: {
  project: Project;
  onAdd: (title: string) => Promise<void>;
  addPending: boolean;
  onRefresh: () => void;
  onRunAutonomously: () => void;
  onToggleAutonomous: (on: boolean) => void;
  onAskReprioritize: () => void;
  onCurate: (instruction: string) => void;
  curatePending: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  // Curate used to collect its optional focus through `window.prompt`, which cannot be styled,
  // freezes the whole tab while it is open, and renders as an "app.mosaera.dev says" box that
  // reads like a phishing prompt rather than part of the product. "Add item" directly above
  // already had the inline pattern, so curate uses the same one instead of inventing a modal.
  const [curating, setCurating] = useState(false);
  const [focus, setFocus] = useState("");

  const items = project.backlog ?? [];
  const counts = backlogCounts(items);
  const running = counts.inProgress > 0;
  const showAutonomous = project.autonomous && counts.todo > 0 && !running;

  async function submit() {
    const t = title.trim();
    if (!t) return;
    await onAdd(t);
    setTitle("");
    setAdding(false);
  }

  function submitCurate() {
    // An EMPTY focus is meaningful — it is the full pass — so unlike `submit` this never bails on
    // a blank field. The row closes immediately; the button's own pending state reports progress.
    onCurate(focus.trim());
    setFocus("");
    setCurating(false);
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <h1 className="font-sans text-2xl font-bold tracking-tight">Backlog</h1>
      <span className="font-mono text-xs tabular-nums text-muted-foreground">
        {backlogSummary(counts)}
      </span>

      <div className="ms-auto flex flex-wrap items-center gap-2">
        {adding ? (
          <>
            <Input
              autoFocus
              placeholder="New backlog item title"
              aria-label="New backlog item title"
              className="w-64 font-mono text-xs"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submit();
                if (e.key === "Escape") setAdding(false);
              }}
            />
            <Button size="sm" variant="secondary" disabled={addPending} onClick={() => void submit()}>
              Add
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <>
            {showAutonomous && (
              <Button size="sm" onClick={onRunAutonomously}>
                Run autonomously ▸
              </Button>
            )}
            {/* Autonomous is a persistent per-project setting. Without this
                toggle it could only be set at project creation, so a project
                made without it could never be run autonomously. */}
            <Button
              size="sm"
              variant={project.autonomous ? "secondary" : "ghost"}
              className={project.autonomous ? undefined : "text-muted-foreground"}
              aria-pressed={project.autonomous}
              title={
                project.autonomous
                  ? "Sweep is autonomous: cleanly-delivered items chain to the next. Does NOT change a single item's Run button, which is always guided — choose the mode on the item itself."
                  : "Make the sweep autonomous: auto-approve and chain through the backlog. A single item's Run button stays guided either way."
              }
              onClick={() => onToggleAutonomous(!project.autonomous)}
            >
              <Zap data-icon="inline-start" />
              {/* Named for what it governs — the SWEEP. Labelled "Autonomous on" it read as a
                  global posture, so an operator flipped it, pressed a card's Run, and got a
                  guided run (2026-08-06). */}
              Auto-sweep {project.autonomous ? "on" : "off"}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
              <Plus data-icon="inline-start" />
              Add item
            </Button>
            {curating ? (
              <>
                <Input
                  autoFocus
                  placeholder="What should Quincy focus on? (optional)"
                  aria-label="Curation focus (optional)"
                  className="w-72 font-mono text-xs"
                  value={focus}
                  onChange={(e) => setFocus(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitCurate();
                    if (e.key === "Escape") setCurating(false);
                  }}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={curatePending}
                  onClick={submitCurate}
                >
                  {curatePending ? "Curating…" : "Curate"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setCurating(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                className="text-muted-foreground"
                disabled={curatePending}
                title="Ask Quincy to propose reordering, dependencies, and clarity edits"
                onClick={() => setCurating(true)}
              >
                <Sparkles data-icon="inline-start" />
                {curatePending ? "Curating…" : "Curate backlog"}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="text-muted-foreground"
              onClick={onAskReprioritize}
            >
              <MessageSquare data-icon="inline-start" />
              Ask PM to reprioritize
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-muted-foreground"
              onClick={onRefresh}
            >
              <RefreshCw data-icon="inline-start" />
              Refresh backlog…
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
