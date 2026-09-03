/* One readiness row, shared by every step of the first-run wizard (#119).
 *
 * Shared by the environment step and anything else reporting readiness, so a copy per screen is
 * exactly how two of them would start disagreeing about what "needs fixing" looks like.
 */

import { CheckCircle2, CircleAlert, CircleDashed, Info } from "lucide-react";

import { CopyButton } from "@/components/ui/CopyButton";
import { cn } from "@/lib/utils";

import type { PreflightCheck } from "../../api/firstRun";
import { STATUS_LABEL, statusTone } from "../../lib/firstRun";

const STATUS_ICON = {
  ok: CheckCircle2,
  fail: CircleAlert,
  unknown: CircleDashed,
  note: Info,
} as const;

/** One readiness row: the answer, the detail, and — when there is one — the exact command. */
export function CheckRowView({ check }: { check: PreflightCheck }) {
  const Icon = STATUS_ICON[check.status] ?? CircleDashed;
  const tone = statusTone(check.status);
  return (
    <div className="flex items-start gap-2">
      <Icon
        aria-hidden
        className={cn(
          "mt-0.5 size-4 shrink-0",
          tone === "success" ? "text-emerald-500" : tone === "amber" ? "text-primary" : "text-muted-foreground",
        )}
      />
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-[13px] text-foreground">
          {check.label}{" "}
          <span className="text-[11px] text-muted-foreground">
            — {STATUS_LABEL[check.status] ?? check.status}
          </span>
        </span>
        <span className="text-[11.5px] leading-relaxed text-muted-foreground">{check.detail}</span>
        {check.fix && (
          <span className="flex items-center gap-1.5">
            <code className="min-w-0 truncate rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[10.5px] text-foreground/90">
              {check.fix}
            </code>
            <CopyButton text={check.fix} label="Copy the fix" />
          </span>
        )}
      </div>
    </div>
  );
}
