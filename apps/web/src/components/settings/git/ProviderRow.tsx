import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { TONE_BADGE } from "../../StatusBadge";

/** One forge on the Git index: mark, name, one line of what connecting it does, and the
 *  state it is in. A row is a link, not a button with an onClick — the panel behind it is a
 *  real route (`/settings/git/:provider`), so it deep-links, opens in a new tab, and keeps
 *  the back button honest.
 *
 *  `state` is deliberately a short word rather than a sentence: the index answers "what is
 *  this workspace connected to?" at a glance, and the panel behind it owns the explanation. */
export function ProviderRow({
  to,
  mark,
  name,
  description,
  state,
  tone = "neutral",
}: {
  to: string;
  mark: React.ReactNode;
  name: string;
  description: string;
  state?: string;
  tone?: "neutral" | "success" | "amber";
}) {
  return (
    <Link
      to={to}
      className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-muted/30"
    >
      <span className="shrink-0 text-foreground">{mark}</span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">{name}</span>
          {state && (
            <Badge
              className={cn(
                "font-mono text-[10px] uppercase",
                tone === "success"
                  ? TONE_BADGE.success
                  : tone === "amber"
                    ? TONE_BADGE.amber
                    : TONE_BADGE.neutral,
              )}
            >
              {state}
            </Badge>
          )}
        </span>
        <span className="truncate text-[12.5px] text-muted-foreground">{description}</span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground/70" aria-hidden />
    </Link>
  );
}
