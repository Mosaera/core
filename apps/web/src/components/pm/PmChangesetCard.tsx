import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, MessageCircleQuestion, PencilLine, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import { api, type BacklogItem, type ChangesetOp } from "../../api/client";
import { describeOp } from "../backlog/ChangesetReview";
import { CardHead } from "../overview/bits";

/* TODO: changesets are response-local today — the backend stores only the reply
   text. When persisted proposal objects exist, this card should hydrate from
   them so decisions survive a reload. */

type ProposalState =
  | "idle"
  | "editing"
  | "denying"
  | "busy"
  | "approved"
  | "revision_requested"
  | "declined";

const DENY_REASONS = ["Wrong priority", "Too aggressive", "Needs more detail", "Not aligned", "Other"];

/** Inline card for a backlog changeset Quincy proposes in chat — add, reorder,
 *  enhance, split, merge, lock, delete, set-dependencies — with a real approval
 *  workflow. Approve applies the WHOLE changeset atomically (once); edits/deny/
 *  why go back to Quincy as chat messages, the real feedback channel. */
export function PmChangesetCard({
  projectId,
  ops,
  items,
  onSend,
  sendBusy,
  onResolved,
}: {
  projectId: string;
  ops: ChangesetOp[];
  /** live backlog, so op ids resolve to item names in the summary */
  items: BacklogItem[];
  /** sends a follow-up chat message to Quincy (the real feedback channel) */
  onSend: (text: string) => void;
  sendBusy: boolean;
  /** the operator settled this card — record it so a reload does not bring it back. Optional so
   *  a caller with no stored proposal (an unsaved turn) needs no change. */
  onResolved?: (status: "accepted" | "dismissed") => void;
}) {
  const qc = useQueryClient();
  const [state, setState] = useState<ProposalState>("idle");
  const [denyReason, setDenyReason] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const editRef = useRef<HTMLTextAreaElement>(null);

  const titleOf = (id: number) => items.find((i) => i.id === id)?.title ?? `#${id}`;

  useEffect(() => {
    if (state === "editing") editRef.current?.focus();
  }, [state]);

  const approve = useMutation({
    mutationFn: () => api.applyChangeset(projectId, ops),
    onSuccess: () => {
      setState("approved"); // terminal: re-approval impossible
      onResolved?.("accepted");
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["backlog", projectId] });
    },
    onError: () => setState("idle"),
  });

  function startApprove() {
    if (state !== "idle") return;
    setState("busy");
    approve.mutate();
  }

  function sendEdits() {
    const note = feedback.trim();
    if (!note) return;
    onSend(`Please revise this proposal: ${note}`);
    setState("revision_requested");
    // A revision request settles THIS proposal — the reply carries a new one. Leaving it open
    // would restore the superseded card on the next load, beside its own replacement.
    onResolved?.("dismissed");
  }

  function sendDeny(reason: string) {
    setDenyReason(reason);
    onSend(`I'm declining this proposal. Reason: ${reason.toLowerCase()}.`);
    setState("declined");
    onResolved?.("dismissed");
  }

  const decided = state === "approved" || state === "revision_requested" || state === "declined";

  return (
    <Card size="sm" className={decided ? "ring-border" : "ring-primary/30"}>
      <CardHeader>
        <CardHead icon={Sparkles} tone={decided ? "neutral" : "amber"}>
          Proposed change{ops.length === 1 ? "" : "s"} · {ops.length}
        </CardHead>
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5">
        <ul className="flex flex-col gap-2">
          {ops.map((op, i) => {
            const { icon: Icon, headline, detail, why } = describeOp(op, titleOf);
            return (
              <li key={i} className="flex items-start gap-2">
                <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-[13px] font-medium leading-snug">{headline}</span>
                  {detail.map((d, j) => (
                    <span key={j} className="text-xs leading-snug text-muted-foreground">
                      {d}
                    </span>
                  ))}
                  {why && (
                    <span className="text-xs italic leading-snug text-muted-foreground/70">
                      {why}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>

        {state === "approved" && (
          <p className="flex items-center gap-1.5 text-[13px] font-medium text-success">
            <CircleCheck className="size-4" /> Approved — {ops.length} change
            {ops.length === 1 ? "" : "s"} applied
          </p>
        )}
        {state === "revision_requested" && (
          <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
            <PencilLine className="size-4" /> Revision requested — waiting on Quincy's next reply
          </p>
        )}
        {state === "declined" && (
          <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
            <CircleX className="size-4" /> Declined — {denyReason?.toLowerCase()}
          </p>
        )}
        {approve.isError && (
          <p role="alert" className="text-xs text-destructive">
            {String(approve.error)}
          </p>
        )}

        {state === "editing" && (
          <div className="flex flex-col gap-2">
            <label htmlFor="changeset-feedback" className="text-[13px] text-muted-foreground">
              What should change before approval?
            </label>
            <textarea
              id="changeset-feedback"
              ref={editRef}
              rows={3}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              className="w-full resize-y rounded-md border border-input bg-background px-2.5 py-2 font-sans text-sm shadow-none outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={sendEdits} disabled={!feedback.trim() || sendBusy}>
                Send feedback
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setState("idle")}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {state === "denying" && (
          <div className="flex flex-wrap items-center gap-1.5">
            {DENY_REASONS.map((r) => (
              <Button
                key={r}
                size="sm"
                variant="outline"
                className="h-7 rounded-full font-mono text-[11px]"
                onClick={() => sendDeny(r)}
                disabled={sendBusy}
              >
                {r}
              </Button>
            ))}
            <Button size="sm" variant="ghost" className="h-7" onClick={() => setState("idle")}>
              Cancel
            </Button>
          </div>
        )}

        {(state === "idle" || state === "busy") && (
          <div className="flex flex-wrap gap-2 pt-0.5">
            <Button size="sm" onClick={startApprove} disabled={state === "busy"}>
              {state === "busy" ? "Applying…" : "Approve"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setState("editing")}
              disabled={state === "busy"}
            >
              Request edits
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setState("denying")}
              disabled={state === "busy"}
            >
              Deny
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-muted-foreground"
              onClick={() => onSend("Why do you recommend this?")}
              disabled={state === "busy" || sendBusy}
            >
              <MessageCircleQuestion /> Ask why
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
