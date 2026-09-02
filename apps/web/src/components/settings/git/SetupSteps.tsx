import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

export type StepState = "done" | "current" | "pending";

/** A setup sequence rendered as a checklist rather than a paged wizard.
 *
 *  The GitHub setup is three trips to GitHub — register the app, install it, and (optionally) add
 *  an OAuth App so repositories can be created. It used to be a one-page wizard that handed off to
 *  a panel of unrelated-looking sections, so the stepper said "1 of 3" and then never moved, and
 *  the two remaining trips were things you had to notice rather than be led to.
 *
 *  A checklist fits this better than a wizard because the steps are not modal: they are done at
 *  different times, on a different site, and one of them is optional. Showing all three at once
 *  with their real state answers "what is left?" without anyone having to remember. */
export function SetupSteps({ children }: { children: React.ReactNode }) {
  return <ol className="flex flex-col items-stretch gap-2">{children}</ol>;
}

export function SetupStep({
  index,
  state,
  title,
  optional,
  children,
}: {
  index: number;
  state: StepState;
  title: string;
  optional?: boolean;
  children?: React.ReactNode;
}) {
  const done = state === "done";
  return (
    <li
      className={cn(
        "flex gap-3 rounded-lg p-4 ring-1 transition-colors",
        state === "current" ? "bg-card ring-white/12" : "ring-white/[0.06]",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-medium",
          done
            ? "bg-success/20 text-success"
            : state === "current"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground",
        )}
      >
        {done ? <Check className="size-3" /> : index}
      </span>

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "text-sm font-medium",
              state === "pending" ? "text-muted-foreground" : "text-foreground",
            )}
          >
            {title}
          </span>
          {optional && (
            <span className="rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
              optional
            </span>
          )}
          {/* The state is said in words as well as colour — a green ring is not a status for
              anyone reading this without colour. */}
          {done && <span className="text-[11.5px] text-success">done</span>}
        </div>
        {children}
      </div>
    </li>
  );
}
