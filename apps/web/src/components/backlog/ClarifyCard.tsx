import { SquareCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { ItemClarification } from "../../api/client";
import { ConsoleLabel } from "../overview/bits";

export const TEXTAREA_CLS =
  "min-h-24 w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

/** An intake question (ADR-0080) or the ESCALATE arm's (ADR-0091): the operator resolves it here.
 *  Accepting rewrites the acceptance via the validated changeset path server-side (operator
 *  acceptance is what makes it binding). Shared by the backlog item sheet and the run ledger's
 *  interactive clarification row.
 *
 *  `proposal_kind` decides whether proposals are ACTIONS or CONTEXT. Intake proposals are complete
 *  replacement acceptance texts, so they stay one-click. The ESCALATE arm's are directions for a
 *  human ("amend the criteria so tests/x.py can pass") — rendering those as buttons is what let one
 *  click make that sentence the item's bar. A missing kind is treated as `direction`: every row
 *  written before ADR-0091 lacks the field, and trusting them would keep the defect alive.
 *
 *  The action set is deliberately NOT a gradient toward the easy answer. Before this, the only
 *  zero-friction actions lowered the bar, keeping it cost typing, and the free action was labelled
 *  "Dismiss" — so *the bar is right, the code is wrong* had no representation at all. */
export function ClarifyCard({
  clarification,
  busy,
  onResolve,
}: {
  clarification: ItemClarification;
  busy: boolean;
  onResolve: (body: {
    accepted_proposal_index?: number;
    edited_text?: string;
    rejected?: boolean;
    disposition?: "bar_stands_retry";
  }) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [edited, setEdited] = useState("");
  const actionable = clarification.proposal_kind === "acceptance";
  return (
    <section
      className="flex flex-col gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3"
      aria-label="Clarification needed"
    >
      <ConsoleLabel>Quincy asks · clarification needed</ConsoleLabel>
      <p className="text-sm leading-snug">
        <span className="font-mono text-xs text-muted-foreground">“{clarification.claim_text}”</span>
        {clarification.why_unbindable && (
          <span className="mt-1 block text-xs text-muted-foreground">
            {clarification.why_unbindable}
          </span>
        )}
      </p>
      <div className="flex flex-col gap-1.5">
        {clarification.proposals.map((proposal, i) =>
          actionable ? (
            <Button
              key={i}
              variant="outline"
              size="sm"
              disabled={busy}
              className="h-auto justify-start whitespace-normal py-1.5 text-left text-xs"
              onClick={() => void onResolve({ accepted_proposal_index: i })}
            >
              <SquareCheck className="mr-1.5 size-3 shrink-0" />
              {proposal}
            </Button>
          ) : (
            <p key={i} className="pl-1 text-xs leading-snug text-muted-foreground">
              · {proposal}
            </p>
          ),
        )}
      </div>
      {editing ? (
        <div className="flex flex-col gap-1.5">
          <textarea
            aria-label="Edited acceptance"
            className={cn(TEXTAREA_CLS, "font-mono text-xs")}
            placeholder="Write the acceptance you actually want…"
            value={edited}
            onChange={(e) => setEdited(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={busy || !edited.trim()}
              onClick={() => void onResolve({ edited_text: edited })}
            >
              Accept edited
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(true)}>
            {actionable ? "Edit my own" : "Write the acceptance"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => void onResolve({ disposition: "bar_stands_retry" })}
          >
            The bar stands — the code is wrong
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            className="text-muted-foreground"
            onClick={() => void onResolve({ rejected: true })}
          >
            Dismiss
          </Button>
        </div>
      )}
    </section>
  );
}
