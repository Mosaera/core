import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

import type { BranchRef, CommitRef, MrCompose } from "../../api/delivery";

const TEXTAREA_CLS =
  "min-h-24 w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

/** What the compose Sheet edits — the prefill from which a draft starts. */
export interface ComposeDraft {
  /** "project" (one combined MR) or an item id. Drives the submit target + heading. */
  kind: "project" | { itemId: number };
  title: string;
  body: string;
  target: string;
  squash: boolean;
  removeSource: boolean;
}

/** The pre-filled, editable MR form (ADR-0103). Edits the title/full body/target/squash/
 *  delete-source, then hands a MrCompose to the caller. Without the project's api token the
 *  body edits can't survive push-options — the caller shows that caveat. */
export function MrComposeSheet({
  draft,
  branches,
  commits,
  apiTokenPresent,
  busy,
  onSubmit,
  onClose,
}: {
  draft: ComposeDraft | null;
  branches: BranchRef[];
  commits: CommitRef[];
  apiTokenPresent: boolean;
  busy: boolean;
  onSubmit: (kind: ComposeDraft["kind"], compose: MrCompose) => void;
  onClose: () => void;
}) {
  return (
    <Sheet open={Boolean(draft)} onOpenChange={(open) => !open && onClose()}>
      {draft && (
        <SheetContent
          side="right"
          className="overflow-y-auto sm:max-w-lg [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]"
        >
          <ComposeBody
            key={typeof draft.kind === "string" ? "project" : draft.kind.itemId}
            draft={draft}
            branches={branches}
            commits={commits}
            apiTokenPresent={apiTokenPresent}
            busy={busy}
            onSubmit={onSubmit}
          />
        </SheetContent>
      )}
    </Sheet>
  );
}

function ComposeBody({
  draft,
  branches,
  commits,
  apiTokenPresent,
  busy,
  onSubmit,
}: {
  draft: ComposeDraft;
  branches: BranchRef[];
  commits: CommitRef[];
  apiTokenPresent: boolean;
  busy: boolean;
  onSubmit: (kind: ComposeDraft["kind"], compose: MrCompose) => void;
}) {
  const [title, setTitle] = useState(draft.title);
  const [body, setBody] = useState(draft.body);
  const [target, setTarget] = useState(draft.target);
  const [squash, setSquash] = useState(draft.squash);
  const [removeSource, setRemoveSource] = useState(draft.removeSource);
  // `labelsTouched` is the difference between "no opinion" and "no labels". Untouched → the field
  // is omitted from the payload and GitLab keeps whatever the MR already has; touched → we send
  // the list, and an empty one legitimately clears them. Before this the sheet sent `labels: []`
  // on EVERY submit, which the server faithfully read as "clear", wiping the labels off an
  // already-open MR on re-compose.
  const [labels, setLabels] = useState("");
  const [labelsTouched, setLabelsTouched] = useState(false);
  // A2: which commits to include. Empty set = the whole branch (the default).
  const [picked, setPicked] = useState<Set<string>>(new Set());
  useEffect(() => {
    setTitle(draft.title);
    setBody(draft.body);
    setTarget(draft.target);
    setSquash(draft.squash);
    setRemoveSource(draft.removeSource);
    setLabels("");
    setLabelsTouched(false);
    setPicked(new Set());
  }, [draft]);

  const isProject = typeof draft.kind === "string";
  const label =
    typeof draft.kind === "string" ? "Combined project MR" : `Item #${draft.kind.itemId} MR`;
  // The commit-picker only makes sense for the combined MR (items carry one commit) and needs
  // the api token (the cherry-picked branch is opened via the REST path).
  const showCommits = isProject && apiTokenPresent && commits.length > 1;
  function toggle(sha: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(sha)) next.delete(sha);
      else next.add(sha);
      return next;
    });
  }

  return (
    <>
      <SheetHeader>
        <SheetTitle>Compose merge request</SheetTitle>
        <SheetDescription>
          {label} — review and edit before it's sent. You still merge it in GitLab.
        </SheetDescription>
      </SheetHeader>

      <div className="flex flex-col gap-4 px-4 py-3">
        {!apiTokenPresent && (
          <p className="rounded-md bg-amber-500/10 px-3 py-2 text-[12px] leading-relaxed text-amber-600 dark:text-amber-400">
            No project <span className="font-mono">api</span>-scoped token — the body can't survive
            the push-options transport, so title/body/labels are ignored and the MR opens with the
            defaults. Add an api token in project settings to edit it faithfully.
          </p>
        )}

        <Field label="Title">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} disabled={!apiTokenPresent} />
        </Field>

        <Field label="Description">
          <textarea
            className={cn(TEXTAREA_CLS, "min-h-48 font-mono text-xs")}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            disabled={!apiTokenPresent}
          />
        </Field>

        <Field label="Target branch">
          {branches.length > 0 ? (
            <select
              className={cn(TEXTAREA_CLS, "min-h-0 py-2")}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              {branches.some((b) => b.name === target) ? null : <option value={target}>{target}</option>}
              {branches.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name}
                  {b.merged ? " (merged)" : ""}
                </option>
              ))}
            </select>
          ) : (
            <Input value={target} onChange={(e) => setTarget(e.target.value)} />
          )}
        </Field>

        {apiTokenPresent && (
          <Field label="Labels">
            <Input
              value={labels}
              placeholder="comma-separated — leave blank to keep the MR's current labels"
              onChange={(e) => {
                setLabels(e.target.value);
                setLabelsTouched(true);
              }}
            />
          </Field>
        )}

        {showCommits && (
          <Field label={`Commits (${picked.size || "all"} of ${commits.length})`}>
            <div className="flex max-h-56 flex-col gap-1 overflow-y-auto rounded-lg border border-input p-2 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
              {commits.map((c) => (
                <label key={c.sha} className="flex cursor-pointer items-start gap-2 text-[12px]">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={picked.has(c.sha)}
                    onChange={() => toggle(c.sha)}
                  />
                  <span className="min-w-0">
                    <span className="font-mono text-[10.5px] text-muted-foreground">{c.short}</span>{" "}
                    {c.subject}
                  </span>
                </label>
              ))}
            </div>
            <span className="text-[11px] text-muted-foreground">
              None selected = all commits. Selecting a subset cherry-picks just those into the MR.
            </span>
          </Field>
        )}

        <Toggle checked={squash} onChange={setSquash} label="Squash commits on merge" />
        <Toggle
          checked={removeSource}
          onChange={setRemoveSource}
          label="Delete source branch on merge"
          // Pre-checked for a combined MR, and now reachable from the Changes tab too — a
          // destructive default deserves to say what it does rather than sit unlabelled.
          note="GitLab removes the branch once this merges. The commits live on in the target."
        />
      </div>

      <SheetFooter>
        <Button
          disabled={busy}
          onClick={() =>
            onSubmit(draft.kind, {
              ...(apiTokenPresent ? { title, body } : {}),
              ...(apiTokenPresent && labelsTouched
                ? {
                    labels: labels
                      .split(",")
                      .map((l) => l.trim())
                      .filter(Boolean),
                  }
                : {}),
              target_branch: target,
              squash,
              remove_source_branch: removeSource,
              ...(picked.size > 0 ? { commit_shas: [...picked] } : {}),
            })
          }
        >
          {busy ? "Opening…" : "Open merge request"}
        </Button>
      </SheetFooter>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  note,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  note?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 text-[13px]">
      <input
        type="checkbox"
        className="mt-1"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="flex flex-col">
        {label}
        {note && <span className="text-[11.5px] text-muted-foreground">{note}</span>}
      </span>
    </label>
  );
}
