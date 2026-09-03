import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ClipboardCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { useAuth } from "../../api/authContext";
import { api, type ProjectSetup } from "../../api/client";
import {
  BUDGET_HINT,
  BUDGET_NO_DATA,
  draftChangesSomething,
  initialDraft,
  LEG_LABEL,
  PARK_EXPLAINER,
  POSTURE_AXIS_NOTE,
  POSTURE_HINT,
  PROCTOR_DEPLOYMENT_WIDE,
  RUN_MODE_DEFAULT_NOTE,
  RUN_MODE_HINT,
  RUN_MODE_LABEL,
  type SetupDraft,
  SHAPE_EXPECTATION,
  SHAPE_HEADLINE,
  STRENGTH_PLAIN,
  testerKnobNote,
  unverifiableWarning,
} from "../../lib/projectSetup";
import { ConsoleLabel } from "../overview/bits";

/* Project setup (#121): the choices that decide whether this project's runs can succeed.
 *
 * A CHECKLIST, NOT A WIZARD, and the difference is load-bearing. It sits beside the Quincy chat
 * rather than in front of it — the chat stays usable the whole time — and it arrives PRE-FILLED
 * with a detected recommendation behind a single accept. The evidence on activation is blunt in
 * both directions: a blocking multi-step wizard suppresses people getting to first value, and a
 * form of empty fields is where they stop. So the only row that is open by default is the ONE that
 * actually decides whether a run can conclude; the rest sit at safe defaults, one click away.
 *
 * Nothing here is a control. It writes real settings the engine already had — the gate's authority
 * is untouched, and the recommendation only ever turns verification ON.
 */
export function SetupPanel({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const { isAdmin } = useAuth();
  const { data, isError } = useQuery({
    queryKey: ["setup", projectId],
    queryFn: () => api.projectSetup(projectId),
  });

  // null until the operator touches something, then their edits — so a refetch cannot stamp over
  // what they are in the middle of typing, and the pre-fill stays derived from the server.
  const [edited, setEdited] = useState<SetupDraft | null>(null);
  const [openRow, setOpenRow] = useState<string>("oracle");
  const [dismissed, setDismissed] = useState(false);

  const save = useMutation({
    mutationFn: (draft: SetupDraft) =>
      api.saveProjectSetup(projectId, {
        run_mode: draft.run_mode,
        test_cmd: draft.test_cmd,
        budget_usd: draft.budget_usd,
        completed: true,
        // Governance and deployment-global config are omitted unless this user may set them; the
        // server reads an omitted field as "leave alone", so a member's save can never move them.
        ...(isAdmin ? { posture: draft.posture, tester_enabled: draft.tester_enabled } : {}),
      }),
    onSuccess: (next) => {
      qc.setQueryData(["setup", projectId], next);
      setDismissed(true);
    },
  });

  // A failed read used to render NOTHING — the checklist that decides whether a run can conclude
  // simply was not there, and nothing said why. Loading still renders nothing (it arrives in a
  // moment); a failure says so.
  if (isError) {
    return (
      <section
        role="alert"
        className="flex flex-col gap-1 rounded-lg bg-card p-4 ring-1 ring-white/12"
      >
        <ConsoleLabel>Project setup</ConsoleLabel>
        <p className="text-[12px] leading-relaxed text-muted-foreground">
          Couldn't load this project's setup. Reload the page — until it loads, the run mode and
          the checks that decide whether a run can conclude are whatever they already were.
        </p>
      </section>
    );
  }
  if (!data) return null;
  // Answered → the one-line summary; the full card is a first-run prompt, and Settings is where
  // it gets revisited. `dismissed` covers the moment right after a save, before the refetch.
  if (data.completed_at || dismissed) return <SetupSummary setup={data} />;

  const draft = edited ?? initialDraft(data);
  const set = (patch: Partial<SetupDraft>) => setEdited({ ...draft, ...patch });
  const warning = unverifiableWarning(data, draft);
  const shape = data.repo_shape?.shape ?? "";
  const proposing = draftChangesSomething(data, draft);

  return (
    <section className="flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-white/12">
      <ConsoleLabel>Project setup</ConsoleLabel>

      {/* The repo, as MEASURED — or an honest "not yet" while intake is still cloning. */}
      {!data.available ? (
        <p className="text-sm leading-relaxed text-muted-foreground">
          {data.reason ?? "The repository has not been read yet."}
        </p>
      ) : (
        <ShapeHeader setup={data} shape={shape} />
      )}

      <Row
        id="oracle"
        title="How work gets checked"
        summary={oracleSummary(data, draft)}
        openRow={openRow}
        setOpenRow={setOpenRow}
      >
        <OracleRow setup={data} draft={draft} set={set} isAdmin={isAdmin} />
      </Row>

      <Row
        id="mode"
        title="How much it asks you"
        summary={RUN_MODE_LABEL[draft.run_mode] ?? draft.run_mode}
        openRow={openRow}
        setOpenRow={setOpenRow}
      >
        <div className="flex flex-col gap-1.5">
          <Select value={draft.run_mode} onValueChange={(v) => set({ run_mode: v ?? draft.run_mode })}>
            <SelectTrigger aria-label="Run mode" className="w-48 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {data.choices.run_mode.map((m) => (
                <SelectItem key={m} value={m} className="text-sm">
                  {RUN_MODE_LABEL[m] ?? m}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[11.5px] leading-relaxed text-muted-foreground">
            {RUN_MODE_HINT[draft.run_mode]}
          </p>
          <p className="text-[11.5px] leading-relaxed text-muted-foreground/80">
            {RUN_MODE_DEFAULT_NOTE}
          </p>
        </div>
      </Row>

      <Row
        id="posture"
        title="What this deployment permits"
        summary={draft.posture}
        openRow={openRow}
        setOpenRow={setOpenRow}
      >
        <div className="flex flex-col gap-1.5">
          <Select
            value={draft.posture}
            onValueChange={(v) => set({ posture: v ?? draft.posture })}
            disabled={!isAdmin}
          >
            <SelectTrigger aria-label="Governance posture" className="w-48 text-sm capitalize">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {data.choices.posture.map((p) => (
                <SelectItem key={p} value={p} className="text-sm capitalize">
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[11.5px] leading-relaxed text-muted-foreground">
            {POSTURE_HINT[draft.posture]}
          </p>
          <p className="text-[11.5px] leading-relaxed text-muted-foreground/80">
            {POSTURE_AXIS_NOTE}
          </p>
        </div>
      </Row>

      <Row
        id="budget"
        title="What it may spend"
        summary={draft.budget_usd === null ? "no cap" : `$${draft.budget_usd}/mo`}
        openRow={openRow}
        setOpenRow={setOpenRow}
      >
        <div className="flex flex-col gap-1.5">
          <Input
            aria-label="Monthly spend cap in USD"
            inputMode="decimal"
            placeholder="no cap"
            value={draft.budget_usd === null ? "" : String(draft.budget_usd)}
            onChange={(e) => {
              const raw = e.target.value.trim();
              const n = Number(raw);
              set({ budget_usd: raw === "" || Number.isNaN(n) ? null : n });
            }}
            className="w-32"
          />
          <p className="text-[11.5px] leading-relaxed text-muted-foreground">{BUDGET_HINT}</p>
          {/* The honest absence, not a "typical" figure. */}
          <p className="text-[11.5px] leading-relaxed text-muted-foreground/80">{BUDGET_NO_DATA}</p>
        </div>
      </Row>

      {warning && (
        <p role="alert" className="border-l-2 border-primary/60 pl-3 text-[12px] leading-relaxed text-foreground/85">
          {warning}
        </p>
      )}

      {save.isError && (
        <p role="alert" className="text-xs text-destructive">
          {save.error instanceof Error ? save.error.message : String(save.error)}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button onClick={() => save.mutate(draft)} disabled={save.isPending}>
          {save.isPending ? "Saving…" : proposing ? "Looks right" : "Keep these settings"}
        </Button>
        <span className="text-[11px] text-muted-foreground/80">
          You can change any of this later in Settings.
        </span>
      </div>
    </section>
  );
}

/** The measured repo shape + the honest expectation, with the mechanism behind a disclosure.
 *  One line up front and the explanation on demand: the caveats are what build trust, and a
 *  paragraph of them before anything has happened is what makes people leave. */
function ShapeHeader({ setup, shape }: { setup: ProjectSetup; shape: string }) {
  const [open, setOpen] = useState(false);
  const evidence = setup.repo_shape?.evidence ?? [];
  return (
    <div className="flex flex-col gap-1">
      <p className="text-sm leading-relaxed text-foreground">{SHAPE_HEADLINE[shape] ?? shape}</p>
      {SHAPE_EXPECTATION[shape] && (
        <p className="text-[12px] leading-relaxed text-muted-foreground">
          {SHAPE_EXPECTATION[shape]}
        </p>
      )}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="self-start border-0 bg-transparent p-0 text-[11px] text-primary underline-offset-2 hover:underline"
      >
        {open ? "Hide" : "What this means"}
      </button>
      {open && (
        <div className="flex flex-col gap-1.5 border-l-2 border-white/12 pl-3">
          <p className="text-[12px] leading-relaxed text-muted-foreground">{PARK_EXPLAINER}</p>
          {/* Provenanced, exactly as the server produced it — the reader can check every line. */}
          <ul className="flex flex-col gap-0.5">
            {evidence.map((line) => (
              <li key={line} className="font-mono text-[10px] text-muted-foreground/80">
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function OracleRow({
  setup,
  draft,
  set,
  isAdmin,
}: {
  setup: ProjectSetup;
  draft: SetupDraft;
  set: (patch: Partial<SetupDraft>) => void;
  isAdmin: boolean;
}) {
  const knobNote = testerKnobNote(setup);
  const pinned = setup.tester_knob?.source === "env";
  const strength = setup.repo_shape?.plan_strength ?? "";
  const standingSuite = setup.oracle_plan?.legs.standing_suite === true;
  return (
    <div className="flex flex-col gap-2.5">
      {/* What the planner already found, so the operator overrides a real thing rather than
          filling in a blank. */}
      {setup.repo_shape && (
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">
          Detected: {setup.repo_shape.plan_reason}
          {STRENGTH_PLAIN[strength] ? ` — ${STRENGTH_PLAIN[strength]}.` : "."}
        </p>
      )}

      <div className="flex items-start gap-2.5">
        <button
          type="button"
          role="switch"
          aria-label="The Assayer writes the acceptance test"
          aria-checked={draft.tester_enabled}
          disabled={!isAdmin || pinned}
          onClick={() => set({ tester_enabled: !draft.tester_enabled })}
          className={cn(
            "relative mt-0.5 h-5 w-9 shrink-0 rounded-full border-0 p-0 transition-colors",
            draft.tester_enabled ? "bg-primary" : "bg-muted",
            !isAdmin || pinned ? "opacity-50" : "cursor-pointer",
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 size-4 rounded-full bg-background transition-all",
              draft.tester_enabled ? "left-4" : "left-0.5",
            )}
          />
        </button>
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-[13px] text-foreground">{LEG_LABEL.tester_vouched}</span>
          <span className="text-[11.5px] leading-relaxed text-muted-foreground">
            {PROCTOR_DEPLOYMENT_WIDE}
          </span>
          {knobNote && (
            <span className="text-[11.5px] leading-relaxed text-muted-foreground/80">
              {knobNote}
            </span>
          )}
          {!isAdmin && !pinned && (
            <span className="text-[11.5px] leading-relaxed text-muted-foreground/80">
              An administrator changes this. Saving here leaves it as it is.
            </span>
          )}
        </div>
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-[13px] text-foreground">{LEG_LABEL.test_cmd}</span>
        <Input
          aria-label="Test command"
          placeholder="e.g. pytest -q"
          value={draft.test_cmd}
          onChange={(e) => set({ test_cmd: e.target.value })}
        />
        <span className="text-[11.5px] leading-relaxed text-muted-foreground">
          Runs in the sandbox with the network off. Naming it says what "validated" means here —
          leave it empty to let the planner decide.
        </span>
      </label>

      {standingSuite && (
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">
          {LEG_LABEL.standing_suite} — this project already has that, so it can vouch on its own.
        </p>
      )}
    </div>
  );
}

/** One collapsible row. Only one is open at a time, and the summary carries the answer so a
 *  collapsed row is still readable — a checklist you have to expand to read is a wizard. */
function Row({
  id,
  title,
  summary,
  openRow,
  setOpenRow,
  children,
}: {
  id: string;
  title: string;
  summary: string;
  openRow: string;
  setOpenRow: (id: string) => void;
  children: React.ReactNode;
}) {
  const open = openRow === id;
  return (
    <div className="flex flex-col gap-2 border-t border-white/8 pt-2.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpenRow(open ? "" : id)}
        className="flex w-full items-center justify-between gap-2 border-0 bg-transparent p-0 text-left"
      >
        <span className="text-[13px] font-medium text-foreground">{title}</span>
        <span className="flex items-center gap-1.5">
          <span className="truncate font-mono text-[11px] text-muted-foreground">{summary}</span>
          <ChevronDown
            className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-180")}
          />
        </span>
      </button>
      {open && children}
    </div>
  );
}

/** Once answered the card collapses to a line. It never nags: an unanswered card is a prompt, an
 *  answered one that keeps asking is noise. */
function SetupSummary({ setup }: { setup: ProjectSetup }) {
  const verified = setup.oracle_plan?.verified_possible ?? false;
  return (
    <section className="flex items-start gap-2 rounded-lg bg-card p-3 ring-1 ring-white/12">
      <ClipboardCheck className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <p className="text-[12px] leading-relaxed text-muted-foreground">
        Setup answered — {RUN_MODE_LABEL[setup.current.run_mode] ?? setup.current.run_mode}
        {verified
          ? ", and work here can be independently checked."
          : ", but nothing can independently check work here yet."}
      </p>
    </section>
  );
}

function oracleSummary(setup: ProjectSetup, draft: SetupDraft): string {
  if (setup.oracle_plan?.legs.standing_suite) return "the existing suite";
  if (draft.tester_enabled) return "the Assayer";
  if (draft.test_cmd.trim()) return "your test command";
  return "nothing yet";
}
