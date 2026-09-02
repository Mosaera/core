import { AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";

/** The house amber attention callout (left rule + triangle): a priced gap or an
 *  honest capability limit — warning-toned, never an error red. One definition for
 *  the pattern previously duplicated in CapabilityLimitNote / GatePanel / ReceiptCard. */
export function AmberCallout({
  title,
  children,
  note,
  className,
  variant = "box",
}: {
  title: string;
  children: React.ReactNode;
  /** Consequence line, amber-emphasized (e.g. "Approving accepts this residual on record."). */
  note?: string;
  className?: string;
  /** "rule" = the open-typography form: a thin amber left accent, no filled box. */
  variant?: "box" | "rule";
}) {
  return (
    <div
      className={cn(
        variant === "rule"
          ? "flex gap-2 border-l-2 border-primary/60 pl-3"
          : "flex gap-2 rounded-md border border-white/12 border-l-[3px] border-l-primary bg-card p-3",
        className,
      )}
    >
      {variant === "box" && <AlertTriangle className="mt-0.5 size-4 shrink-0 text-primary" />}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <div className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-muted-foreground">
          {children}
        </div>
        {note && (
          <p className="mt-1.5 text-[13px] font-medium text-primary">{note}</p>
        )}
      </div>
    </div>
  );
}
