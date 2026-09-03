import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PencilLine, ScrollText, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useAuth } from "../../api/authContext";
import { api, type CharterPosture } from "../../api/client";
import { POSTURE_MEANING } from "../pm/CharterProposalCard";
import { CardHead, EmptyNote } from "./bits";

const POSTURES: CharterPosture[] = ["free", "business", "regulated"];

/** The TRUSTED, operator-authored charter (#42/ADR-0047 §1): goal/constraints/posture.
 *  Display + admin edit. Posture is a <Select> of the three tiers — NEVER free text (the
 *  hard UI rule); goal/constraints are genuinely freeform. Writing is admin-gated (the PUT
 *  goes through adminFetch); a non-admin save surfaces the server's 403. */
export function CharterCard({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["charter", projectId],
    queryFn: () => api.getCharter(projectId),
  });

  const [editing, setEditing] = useState(false);
  const [goal, setGoal] = useState("");
  const [constraints, setConstraints] = useState("");
  const [posture, setPosture] = useState<CharterPosture>("business");

  // Seed the edit fields from the loaded charter whenever the edit form opens.
  useEffect(() => {
    if (editing && data) {
      setGoal(data.goal);
      setConstraints(data.constraints);
      setPosture(data.posture);
    }
  }, [editing, data]);

  const { isAdmin } = useAuth();
  const save = useMutation({
    // Send posture ONLY when this user may change it. A member omits it, which the server reads
    // as "leave it alone" — so saving intent can never silently move governance
    // (ADR-0047 amendment 2026-08-18).
    mutationFn: () =>
      api.putCharter(projectId, isAdmin ? { goal, constraints, posture } : { goal, constraints }),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["charter", projectId] });
    },
  });

  const isSet = Boolean(data && (data.goal || data.constraints || data.created_at));

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardHead icon={ScrollText}>Project charter</CardHead>
        {!editing && (
          <Button size="sm" variant="outline" className="h-7" onClick={() => setEditing(true)}>
            <PencilLine className="size-3.5" />
            {isSet ? "Edit" : "Set charter"}
          </Button>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {isLoading ? (
          <EmptyNote>Loading…</EmptyNote>
        ) : editing ? (
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-muted-foreground">
              Goal
              <textarea
                rows={2}
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                className="w-full resize-y rounded-md border border-input bg-background px-2.5 py-2 font-sans text-sm normal-case tracking-normal text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-muted-foreground">
              Constraints
              <textarea
                rows={2}
                value={constraints}
                onChange={(e) => setConstraints(e.target.value)}
                className="w-full resize-y rounded-md border border-input bg-background px-2.5 py-2 font-sans text-sm normal-case tracking-normal text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>
            <div className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                Autonomy posture
              </span>
              <Select
                value={posture}
                onValueChange={(v) => setPosture(v as CharterPosture)}
                disabled={!isAdmin}
              >
                <SelectTrigger aria-label="Autonomy posture" className="w-40 text-sm capitalize">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {POSTURES.map((p) => (
                    <SelectItem key={p} value={p} className="capitalize">
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span className="text-xs leading-snug text-muted-foreground">
                {POSTURE_MEANING[posture]}
              </span>
              {!isAdmin && (
                <span className="text-xs leading-snug text-muted-foreground/80">
                  Posture is a governance setting — an administrator changes it. Saving here leaves
                  it as it is.
                </span>
              )}
            </div>
            {save.isError && (
              <p role="alert" className="text-xs text-destructive">
                {String(save.error)}
              </p>
            )}
            <div className="flex gap-2">
              <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
                Save charter
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : !isSet ? (
          <EmptyNote>
            No charter yet — shape it with Quincy in chat, or set it here (goal, constraints, and the
            autonomy posture).
          </EmptyNote>
        ) : (
          <dl className="flex flex-col gap-2 text-[13px]">
            <div className="flex flex-col gap-0.5">
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Goal</dt>
              <dd className="leading-snug">{data!.goal || "—"}</dd>
            </div>
            {data!.constraints && (
              <div className="flex flex-col gap-0.5">
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                  Constraints
                </dt>
                <dd className="leading-snug">{data!.constraints}</dd>
              </div>
            )}
            <div className="flex flex-col gap-0.5">
              <dt className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-muted-foreground">
                <ShieldCheck className="size-3.5" /> Autonomy posture
              </dt>
              <dd className="flex flex-col gap-0.5">
                <span className="font-mono text-sm font-semibold capitalize">{data!.posture}</span>
                <span className="text-xs leading-snug text-muted-foreground">
                  {POSTURE_MEANING[data!.posture]}
                </span>
              </dd>
            </div>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}
