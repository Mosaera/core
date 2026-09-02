import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";

import { useDecisions } from "../hooks/useDecisions";

/** The header bell, wired at last (it shipped 2026-08 as a deliberate handler-less placeholder:
 *  "Notifications — coming soon", no state, no dot).
 *
 *  PER PROJECT, by owner decision. There is no cross-project decisions endpoint, and a client-side
 *  fan-out would multiply the endpoint's GitLab REST call by the project count. It reads the SAME
 *  `["decisions", id]` query the Overview band uses, so opening the bell costs zero extra requests
 *  and the 60s interval is the ceiling on that round trip per tab.
 *
 *  The count is BLOCKING conditions only. Standing advisories are dismissible and live in the
 *  band; a bell that counted them would train the operator to ignore the number — the same defect
 *  the blocking/standing tiers were introduced to fix. */
export function NotificationsBell({ projectId }: { projectId: string | null }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [anchor, setAnchor] = useState<{ top: number; right: number } | null>(null);
  const { blocking, standing } = useDecisions(projectId ?? undefined);
  const count = blocking.length;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      // The panel is PORTALED, so it is not inside `wrap` — both must be consulted or the first
      // click inside the panel closes it.
      if (wrap.current?.contains(t) || panel.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const label = !projectId
    ? "Notifications"
    : count > 0
      ? `Notifications — ${count} waiting on you`
      : "Notifications — nothing waiting on you";

  return (
    <div ref={wrap} className="relative">
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="dialog"
        disabled={!projectId}
        onClick={(e) => {
          const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
          setAnchor({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) });
          setOpen((v) => !v);
        }}
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:shadow-[0_0_0_1px_rgba(255,255,255,0.35)]",
          projectId
            ? "text-white/60 hover:bg-white/10 hover:text-white/90"
            : "text-white/25 cursor-default",
        )}
      >
        <span className="relative">
          <Bell className="size-4" />
          {count > 0 && (
            <span
              aria-hidden
              className="absolute -right-1 -top-1 flex size-3.5 items-center justify-center rounded-full bg-amber-500 font-mono text-[9px] font-semibold text-black"
            >
              {count}
            </span>
          )}
        </span>
      </button>
      {/* PORTALED to the body, deliberately. The header carries `backdrop-filter: blur(12px)`,
          which both establishes a containing block AND forces its own compositing layer — an
          absolutely-positioned panel inside it extended ~250px below a 48px bar, so the browser
          had to re-sample and re-blur a six-times-larger backdrop over the whole page behind it.
          On the live instance that stalled the renderer hard enough to time out a screenshot
          (2026-08-23). Rendering outside the blurred layer removes the work entirely; `fixed`
          positioning from the button's rect keeps it under the bell. */}
      {open && projectId && anchor
        ? createPortal(
            <div
              ref={panel}
              role="dialog"
              aria-label="Notifications"
              style={{ top: anchor.top, right: anchor.right }}
              className="fixed z-50 w-80 rounded-lg bg-card p-3 text-left shadow-xl ring-1 ring-white/12"
            >
          {blocking.length === 0 && standing.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">Nothing is waiting on you.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {[...blocking, ...standing].map((d) => (
                <li key={d.id} className="flex flex-col gap-0.5">
                  <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    {d.tier === "standing" ? "Standing" : "Waiting on you"}
                  </span>
                  <span className="text-[13px] font-medium leading-snug">{d.title}</span>
                  <span className="text-[12px] leading-snug text-muted-foreground">
                    {d.summary}
                  </span>
                </li>
              ))}
            </ul>
          )}
              <Link
                to={`/projects/${projectId}/overview`}
                onClick={() => setOpen(false)}
                className="mt-2.5 inline-block font-mono text-[11px] text-primary hover:underline"
              >
                open the worklist →
              </Link>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
