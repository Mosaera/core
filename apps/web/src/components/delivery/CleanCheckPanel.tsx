import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";

import { api } from "../../api/client";
import { ConsoleLabel } from "../overview/bits";

/** "Would this work for someone who cloned it?" — the question the delivery gate never asked (#104).
 *
 *  LedgerCLI delivered 15 gate-approved items with the proof panel reading 14/14 on every axis, and
 *  a fresh clone did not run: three test files imported an undeclared package, and the command every
 *  usage example used did not exist. The gate could not have caught either — the sandbox installs
 *  the project and layers the base image's packages underneath it, so both defects are structurally
 *  invisible there.
 *
 *  Operator-invoked, and informational forever: it never blocks a delivery. A false positive on an
 *  unusual layout costs a sentence on this panel, not a refused merge. */
export function CleanCheckPanel({ projectId }: { projectId: string }) {
  const check = useMutation({ mutationFn: () => api.cleanCheck(projectId) });
  const result = check.data;

  return (
    <section
      aria-label="Clean-clone check"
      className="flex flex-col gap-2 rounded-lg bg-card p-4 ring-1 ring-white/12"
    >
      <ConsoleLabel>From a clean clone</ConsoleLabel>
      <p className="text-[12.5px] leading-relaxed text-muted-foreground">
        The gate proves the code works in the sandbox, where this project is already installed. This
        asks the other question: would someone who cloned it be able to use it?
      </p>

      {result?.status === "passed" && (
        <p className="text-[13px] text-emerald-600 dark:text-emerald-400">
          Nothing found — every import is declared, and the commands the README shows are the ones
          the project provides.
        </p>
      )}

      {result?.status === "failed" && (
        <ul className="flex flex-col gap-1.5">
          {result.findings.map((f, i) => (
            <li key={i} className="text-[12.5px] leading-relaxed text-amber-600 dark:text-amber-400">
              {f}
            </li>
          ))}
        </ul>
      )}

      {/* Never rounded up to a pass. A verdict on a project this could not examine would be the
          same defect the panel exists to catch, one level up. */}
      {result?.status === "not_checked" && (
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">
          Not checked — {result.not_checked_reason || "this project has no manifest to compare against"}.
        </p>
      )}

      {check.error && (
        <p role="alert" className="text-xs text-destructive">
          {check.error instanceof Error ? check.error.message : String(check.error)}
        </p>
      )}

      <Button
        size="sm"
        variant="outline"
        className="w-fit"
        disabled={check.isPending}
        onClick={() => check.mutate()}
      >
        {check.isPending ? "Checking…" : result ? "Check again" : "Check a clean clone"}
      </Button>
    </section>
  );
}
