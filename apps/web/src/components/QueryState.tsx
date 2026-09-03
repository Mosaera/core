import { RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** The shape every `useQuery` result already has — no import of react-query's own type here so
 *  this stays usable for the handful of callers that assemble a query-like object by hand. */
export interface QueryLike {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  refetch: () => void;
}

/** One sentence a human can read from whatever a failed fetch threw. Never the raw
 *  `String(error)` dump (an Error's `.message` when there is one; a flat fallback otherwise —
 *  never JSON, a stack, or `[object Object]`). */
export function summarizeError(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error) return error;
  return "Something went wrong loading this.";
}

/** THE shared loading/error/content wrapper (5E) — 22 of the app's `useQuery` call sites
 *  rendered nothing at all on a failed fetch, the DecisionBand ("waiting on you") worst of
 *  all. One component, adopted mechanically: loading shows a skeleton, an error shows the
 *  summarized failure with a Retry wired to the query's own `refetch`, success renders
 *  `children`. Follows the house card styling (`bg-card` + a hairline ring; destructive tone
 *  only for the error state, never for the quiet loading one). */
export function QueryState({
  query,
  children,
  loadingClassName,
  errorLabel = "Couldn't load this",
  compact = false,
}: {
  query: QueryLike;
  children: React.ReactNode;
  /** Skeleton sizing per call site — a list row and a full card need different heights. */
  loadingClassName?: string;
  /** What failed, in plain terms — the component appends the summarized cause beneath it. */
  errorLabel?: string;
  /** Inline row instead of a padded card, for a surface too small for the full frame. */
  compact?: boolean;
}) {
  if (query.isLoading) {
    return <Skeleton className={cn("h-16 w-full rounded-lg", loadingClassName)} />;
  }
  if (query.isError) {
    return (
      <div
        className={cn(
          "flex flex-wrap items-center gap-2.5 rounded-lg bg-card ring-1 ring-destructive/30",
          compact ? "px-3 py-2" : "p-3",
        )}
      >
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-destructive">{errorLabel}</p>
          <p className="text-[12px] text-muted-foreground">{summarizeError(query.error)}</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => query.refetch()}>
          <RotateCcw /> Retry
        </Button>
      </div>
    );
  }
  return <>{children}</>;
}
