import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, ScrollText, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import { useAuth } from "../../api/authContext";
import { api, type CharterPosture, type CharterProposal } from "../../api/client";
import { CardHead } from "../overview/bits";

/** What each posture actually GRANTS — spelled out so the operator confirms the CONTROL,
 *  not a bare word (ADR-0047 MR3 red-team: the parsed posture is the truth; the chat prose
 *  is decoration and must never be the thing being confirmed). */
export const POSTURE_MEANING: Record<CharterPosture, string> = {
  free: "the agent acts autonomously and you review afterward",
  business: "the agent proposes; you approve each delivery before it ships",
  regulated: "nothing ships without your explicit per-step sign-off",
};

type State = "idle" | "busy" | "confirmed" | "declined";

/** Inline card for a charter Quincy PROPOSED in chat. The card renders the PARSED proposal —
 *  goal, constraints, and posture (with its meaning) — and confirming calls the admin-gated
 *  PUT. The operator confirms THIS structured value, never the surrounding chat prose. */
export function CharterProposalCard({
  projectId,
  proposal,
  onDecline,
  onResolved,
}: {
  projectId: string;
  proposal: CharterProposal;
  /** notify Quincy in chat that the proposal was declined (the feedback channel) */
  onDecline: (reason: string) => void;
  /** the operator settled this card — recorded so a reload does not bring it back. */
  onResolved?: (status: "accepted" | "dismissed") => void;
}) {
  const qc = useQueryClient();
  const { isAdmin } = useAuth();
  const [state, setState] = useState<State>("idle");

  const confirm = useMutation({
    // Confirming writes the TRUSTED row with the PARSED values — exactly what the card displays,
    // so display and write can never diverge. An ADMIN also writes the parsed posture; a member
    // writes intent only and the project's existing posture is left untouched (ADR-0047 amendment
    // 2026-08-18). The proposal's posture stays fully VISIBLE either way — the red-team
    // requirement is that the operator sees the control they are confirming, and a member is
    // told plainly that this half needs an admin.
    mutationFn: () =>
      api.putCharter(
        projectId,
        isAdmin ? proposal : { goal: proposal.goal, constraints: proposal.constraints },
      ),
    onSuccess: () => {
      setState("confirmed");
      onResolved?.("accepted");
      qc.invalidateQueries({ queryKey: ["charter", projectId] });
    },
    onError: () => setState("idle"),
  });

  const decided = state === "confirmed" || state === "declined";

  return (
    <Card size="sm" className={decided ? "ring-border" : "ring-primary/30"}>
      <CardHeader>
        <CardHead icon={ScrollText} tone={decided ? "neutral" : "amber"}>
          Proposed project charter
        </CardHead>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <dl className="flex flex-col gap-2 text-[13px]">
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Goal</dt>
            <dd className="leading-snug">{proposal.goal || <em className="text-muted-foreground">none stated</em>}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Constraints</dt>
            <dd className="leading-snug">
              {proposal.constraints || <em className="text-muted-foreground">none stated</em>}
            </dd>
          </div>
          {/* Posture is the governance control — rendered prominently with its meaning, from
              the PARSED value, so an operator can never confirm a tier they didn't read. */}
          <div className="flex flex-col gap-1 rounded-md border border-amber-500/30 bg-amber-500/5 p-2.5">
            <dt className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-muted-foreground">
              <ShieldCheck className="size-3.5" /> Autonomy posture
            </dt>
            <dd className="flex flex-col gap-0.5">
              <span className="font-mono text-sm font-semibold capitalize">{proposal.posture}</span>
              <span className="text-xs leading-snug text-muted-foreground">
                {POSTURE_MEANING[proposal.posture]}
              </span>
              {!isAdmin && (
                <span className="mt-1 block text-xs leading-snug text-muted-foreground/80">
                  Confirming records the goal and constraints. The posture above is a governance
                  setting only an administrator can change, so it stays as it is for now.
                </span>
              )}
            </dd>
          </div>
        </dl>

        {state === "confirmed" && (
          <p className="flex items-center gap-1.5 text-[13px] font-medium text-success">
            <CircleCheck className="size-4" /> Charter saved
          </p>
        )}
        {state === "declined" && (
          <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
            <CircleX className="size-4" /> Declined — waiting on Quincy's next reply
          </p>
        )}
        {confirm.isError && (
          <p role="alert" className="text-xs text-destructive">
            {String(confirm.error)}
          </p>
        )}

        {state === "idle" && (
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => {
                setState("busy");
                confirm.mutate();
              }}
            >
              Confirm &amp; save charter
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                onDecline("the charter isn't right yet");
                setState("declined");
              }}
            >
              Not yet
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
