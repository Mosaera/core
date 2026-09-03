import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { api } from "../../api/client";
import { ConsoleLabel } from "../overview/bits";

/** The recovery action for a "base drift: …" pause note (task 4D, F12).
 *
 *  `check_base_drift` fails the launch closed on divergence rather than guessing, which is
 *  correct — but before this there was NOTHING in the product to do about it: the project just
 *  stayed stuck with an unexplained launch failure. This names the problem and offers the one
 *  honest fix: force the clone back onto the remote, discarding local-only commits. Typed
 *  confirmation because that discard is real and cannot be undone from here. */
export function DriftRecovery({ projectId, detail }: { projectId: string; detail: string }) {
  const qc = useQueryClient();
  const [confirmText, setConfirmText] = useState("");
  const armed = confirmText.trim().toLowerCase() === "reset";
  const reset = useMutation({
    mutationFn: () => api.resetProjectClone(projectId),
    onSuccess: () => {
      setConfirmText("");
      void qc.invalidateQueries({ queryKey: ["project", projectId] });
      void qc.invalidateQueries({ queryKey: ["branches", projectId] });
    },
  });

  return (
    <div className="flex flex-col gap-2 rounded-md bg-amber-500/10 px-3 py-2.5">
      <p className="text-[11.5px] leading-relaxed text-amber-600 dark:text-amber-400">{detail}</p>
      <p className="text-[11px] leading-relaxed text-muted-foreground/90">
        Forces the project&rsquo;s clone back onto the remote branch, discarding any commits it
        holds that the remote doesn&rsquo;t. This can&rsquo;t be undone from here.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <ConsoleLabel className="text-[10px]">
          Type <span className="text-foreground">reset</span> to confirm
        </ConsoleLabel>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Type reset to confirm"
          placeholder="reset"
          className="h-7 w-32 font-mono text-xs"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
        />
        <Button
          size="sm"
          variant="outline"
          className="text-destructive"
          disabled={!armed || reset.isPending}
          onClick={() => reset.mutate()}
        >
          {reset.isPending ? "Resetting…" : "Reset clone to remote"}
        </Button>
      </div>
      {reset.isSuccess && (
        <p className="font-mono text-[11px] text-success">reset: {reset.data.detail}</p>
      )}
      {reset.isError && (
        <p role="alert" className="text-xs text-destructive">
          {reset.error instanceof Error ? reset.error.message : String(reset.error)}
        </p>
      )}
    </div>
  );
}
