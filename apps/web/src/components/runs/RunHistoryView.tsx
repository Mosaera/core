import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ExternalLink } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

import { api, type BacklogItem, type RunDetail } from "../../api/client";
import {
  buildFileTree,
  fileAnchorId,
  fileDiffStatus,
  flattenTreeFiles,
} from "../../lib/changes";
import { parseDiff } from "../../lib/diff";
import { priorAttemptShapes } from "../../lib/radar";
import { DURABLE_STATUS, liveRunHref, parseReceipt } from "../../lib/runs";
import { AgentAvatar } from "../AgentAvatar";
import { ConsoleLabel, EmptyNote } from "../overview/bits";
import { PmMarkdown } from "../pm/PmMarkdown";
import { DiffPane } from "./DiffPane";
import { deriveLedger } from "../../lib/ledger";
import { decisionOf } from "../../lib/runs";
import { CapabilityLimitNote, WithheldAskNote } from "./evidence";
import { FileTree } from "./FileTree";
import { RecordFooter } from "./RecordFooter";
import { deriveHeroVariant } from "./hero/heroState";
import { RunHero } from "./hero/RunHero";
import { EngineView } from "./engine/EngineView";

/** The durable run-history detail as a commit-style page: a header (title +
 *  facts), the run summary as Quincy's message (the change's description), a CTA
 *  to the full run for the execution detail, then the file tree beside the
 *  stacked per-file diffs. Sourced purely from the persisted record. */
export function RunHistoryView({ detail, projectId }: { detail: RunDetail; projectId?: string }) {
  // Item context for the ledger's intake rows (brief / decomposition fallback /
  // clarification exchange) — the project backlog query is already cached app-wide;
  // ad-hoc runs (no project) skip it.
  const { data: project } = useQuery({
    queryKey: ["project", detail.project_id],
    queryFn: () => api.getProject(detail.project_id!),
    enabled: Boolean(detail.project_id && detail.item_id != null),
  });
  const item: BacklogItem | undefined = (project?.backlog ?? []).find(
    (i) => i.id === detail.item_id,
  );
  // The durable event stream gives gate rows their honest park times.
  const { data: transcriptData } = useQuery({
    queryKey: ["run-transcript", detail.id],
    queryFn: () => api.transcript(detail.id),
    retry: 1,
  });
  const ledgerRows = useMemo(
    () => deriveLedger({ detail, item, events: transcriptData?.events }),
    [detail, item, transcriptData],
  );
  const files = useMemo(
    () => parseDiff(detail.repo_changes[0]?.diff ?? "").filter((f) => f.path),
    [detail],
  );
  const tree = useMemo(
    () =>
      buildFileTree(
        files.map((f) => ({
          path: f.path,
          adds: f.adds,
          dels: f.dels,
          status: fileDiffStatus(f.lines),
        })),
      ),
    [files],
  );
  // Diffs stack in the SAME order the file tree shows (dirs first, then files),
  // so scrolling matches the nav.
  const orderedFiles = useMemo(() => {
    const byPath = new Map(files.map((f) => [f.path, f]));
    return flattenTreeFiles(tree)
      .map((n) => byPath.get(n.path))
      .filter((f): f is (typeof files)[number] => Boolean(f));
  }, [tree, files]);
  const [selected, setSelected] = useState<string | null>(orderedFiles[0]?.path ?? null);
  // While a click-scroll is animating, the observer must not fight the target.
  const scrollingTo = useRef<string | null>(null);

  function selectFile(path: string) {
    setSelected(path);
    scrollingTo.current = path;
    const el = document.getElementById(fileAnchorId(path));
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(() => {
      if (scrollingTo.current === path) scrollingTo.current = null;
    }, 600);
  }

  // Scroll-spy: highlight the file whose diff currently leads the viewport.
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return; // jsdom / SSR
    const order = new Map(orderedFiles.map((f, i) => [f.path, i]));
    const idToPath = new Map(orderedFiles.map((f) => [fileAnchorId(f.path), f.path]));
    const els = orderedFiles
      .map((f) => document.getElementById(fileAnchorId(f.path)))
      .filter((e): e is HTMLElement => e != null);
    if (els.length === 0) return;

    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const path = idToPath.get(entry.target.id);
          if (!path) continue;
          if (entry.isIntersecting) visible.add(path);
          else visible.delete(path);
        }
        if (scrollingTo.current || visible.size === 0) return;
        let top: string | null = null;
        let topIdx = Infinity;
        for (const path of visible) {
          const idx = order.get(path) ?? Infinity;
          if (idx < topIdx) {
            topIdx = idx;
            top = path;
          }
        }
        if (top) setSelected(top);
      },
      { root: null, rootMargin: "-80px 0px -55% 0px", threshold: 0 },
    );
    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [orderedFiles]);

  const heroVariant = deriveHeroVariant({
    status: DURABLE_STATUS[detail.status] ?? detail.status.toLowerCase(),
    gate: null,
    rows: ledgerRows,
    phase: "",
    startedAt: null,
    terminationReason: detail.termination_reason ?? null,
    diagnosis: detail.diagnosis ?? null,
  });
  const runHref = liveRunHref(detail.id, projectId);
  // The summary decision is the description; strip a leading "Summary" heading so
  // it doesn't repeat the bubble's own label.
  const summaryBody = decisionOf(detail, "summary")
    .replace(/^\s*#{0,6}\s*summary\s*[\r\n]+/i, "")
    .trim();

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <RunHero
        rid={detail.id}
        projectId={projectId}
        task={detail.task}
        variant={heroVariant}
        rows={ledgerRows}
        revisions={detail.iterations}
        mergeHref={
          detail.project_id ? `/projects/${detail.project_id}/delivery?view=changes` : undefined
        }
      />

      <CapabilityLimitNote detail={detail} />
      <WithheldAskNote detail={detail} />

      {/* The sealed ledger (#63): the item's whole life as chronological rows —
          brief → claims → gate events → verdict → seal. The engine's tool-level
          transcript is one click away, never the hero. */}
      {summaryBody && (
        <div className="flex items-start gap-3">
          <AgentAvatar actor="Quincy" size={40} className="mt-0.5 ring-1 ring-white/12" />
          <div className="min-w-0 flex-1 rounded-lg rounded-tl-sm bg-card p-3.5 ring-1 ring-white/12">
            <div className="text-sm text-foreground/90">
              <PmMarkdown>{summaryBody}</PmMarkdown>
            </div>
          </div>
        </div>
      )}
      <EngineView
        events={transcriptData?.events}
        detail={detail}
        rows={ledgerRows}
        receipt={parseReceipt(detail)}
        ghosts={priorAttemptShapes(project?.runs ?? [], detail)}
        footer={
          <RecordFooter
            rid={detail.id}
            seal={
              (ledgerRows.find((r) => r.kind === "seal") ?? null) as
                | Extract<(typeof ledgerRows)[number], { kind: "seal" }>
                | null
            }
            detail={detail}
          />
        }
      />
      <Link
        to={runHref}
        className="inline-flex w-fit items-center gap-1.5 font-mono text-[11px] text-primary hover:underline"
      >
        open in run view
        <ArrowRight className="size-3.5" />
      </Link>

      <DeliverMr detail={detail} />

      {files.length === 0 ? (
        <EmptyNote>No file changes were recorded for this run.</EmptyNote>
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-8 lg:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] lg:items-start">
          <div className="flex flex-col gap-2 lg:sticky lg:top-[72px] lg:max-h-[calc(100dvh-96px)] lg:overflow-y-auto lg:[scrollbar-color:var(--border)_transparent] lg:[scrollbar-width:thin]">
            <ConsoleLabel>Files</ConsoleLabel>
            <FileTree nodes={tree} selected={selected} onSelect={selectFile} />
          </div>
          <DiffPane files={orderedFiles} selected={selected} />
        </div>
      )}
    </div>
  );
}

/** Ad-hoc runs (no project) can open a merge request from their own clone;
 *  project runs merge from the project's Changes tab. */
function DeliverMr({ detail }: { detail: RunDetail }) {
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
  const [mr, setMr] = useState<{ url?: string; error?: string; busy?: boolean }>({});
  const canOpenMr = Boolean(cfg?.gitlab && detail.commit_sha && !detail.project_id);
  if (!canOpenMr) return null;

  async function openMr() {
    setMr({ busy: true });
    try {
      setMr({ url: (await api.openMr(detail.id)).url });
    } catch (e) {
      setMr({ error: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <section className="flex flex-col gap-2 rounded-lg bg-card p-4 ring-1 ring-white/12">
      <ConsoleLabel>Deliver</ConsoleLabel>
      {mr.url ? (
        <a
          href={mr.url}
          target="_blank"
          rel="noreferrer"
          className="flex w-fit items-center gap-1 font-mono text-[11px] text-primary hover:underline"
        >
          <ExternalLink className="size-3" />
          merge request opened
        </a>
      ) : (
        <Button size="sm" onClick={() => void openMr()} disabled={mr.busy}>
          {mr.busy ? "Opening…" : "Open merge request"}
        </Button>
      )}
      {mr.error && <p className="font-mono text-[11px] text-destructive">{mr.error}</p>}
    </section>
  );
}
