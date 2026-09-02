import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useMatch } from "react-router-dom";

import { Badge } from "@/components/ui/badge";

import { NotificationsBell } from "./NotificationsBell";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { SidebarTrigger } from "@/components/ui/sidebar";

import { api } from "../api/client";

const SECTION_LABELS: Record<string, string> = {
  start: "Start",
  overview: "Overview",
  pm: "PM",
  backlog: "Backlog",
  changes: "Changes",
  delivery: "Delivery",
  artifacts: "Artifacts",
  runs: "Runs",
  activity: "Activity",
};

const STATIC_LABELS: [prefix: string, label: string][] = [
  ["/run", "New run"],
  ["/runs/", "Run"],
  ["/history/", "Run"],
  ["/settings", "Settings"],
  ["/projects/new", "New project"],
];

/** Orientation crumbs for the current route; page bodies keep their own titles. */
function useCrumbs(): { label: string; to?: string; accent?: boolean }[] {
  const location = useLocation();
  const match = useMatch("/projects/:id/*");
  const projectId = match && match.params.id !== "new" ? (match.params.id ?? null) : null;
  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId as string),
    enabled: projectId !== null,
  });

  if (projectId) {
    const rest = match?.params["*"]?.split("/") ?? [];
    const section = rest[0] || "overview";
    const crumbs: { label: string; to?: string; accent?: boolean }[] = [
      { label: "Projects", to: "/" },
      // The project name carries identity (subtle amber) — the big page titles
      // are retiring tab by tab, starting with the PM chat workspace.
      { label: project?.name ?? projectId, accent: true },
    ];
    // A nested run keeps project focus: … › Runs › <run id>.
    if ((section === "runs" || section === "history") && rest[1]) {
      crumbs.push({ label: "Runs", to: `/projects/${projectId}/runs` });
      crumbs.push({ label: rest[1].slice(0, 8) });
    } else {
      crumbs.push({ label: SECTION_LABELS[section] ?? section });
    }
    return crumbs;
  }
  if (location.pathname === "/projects/new") {
    return [{ label: "Projects", to: "/" }, { label: "New project" }];
  }
  if (location.pathname.startsWith("/settings/")) {
    const section = location.pathname.split("/")[2] || "general";
    const label = section.charAt(0).toUpperCase() + section.slice(1);
    return [{ label: "Settings", to: "/settings" }, { label }];
  }
  for (const [prefix, label] of STATIC_LABELS) {
    if (location.pathname.startsWith(prefix)) return [{ label }];
  }
  return [{ label: "Projects" }];
}

export function AppHeader() {
  const crumbs = useCrumbs();
  // The bell is PER PROJECT: outside a project route there is nothing to notify about, and there
  // is no cross-project decisions endpoint to fan out to (owner decision, 2026-08-22).
  const projectMatch = useMatch("/projects/:id/*");
  const bellProjectId =
    projectMatch && projectMatch.params.id !== "new" ? (projectMatch.params.id ?? null) : null;
  // Engine version (ADR-0055) — a subtle marker so the deploy self-identifies (ml-auto pins it right).
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: Infinity });
  // The login's glass language on the login's white-alpha ramp — but the header, unlike the
  // sidebar, has CONTENT scrolling beneath it, so it keeps a full frosted blur on every screen:
  // an unblurred tint let page text ghost through at 55% and read as a rendering bug (owner,
  // 2026-08-13).
  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b border-white/12 bg-black/50 px-4 shadow-[0_16px_50px_rgba(0,0,0,0.28)] backdrop-blur-md">
      {/* Mobile-only: desktop uses the amber edge control on the sidebar itself.
          The soft amber fill (not just a hairline border) keeps the shape reading
          fully enclosed on high-DPR phones where 1px edges anti-alias away. */}
      <SidebarTrigger className="-ml-1 mr-1 size-8 shrink-0 rounded-md border border-primary/45 bg-primary/10 text-primary hover:bg-primary/20 hover:text-primary md:hidden" />
      <Breadcrumb>
        <BreadcrumbList className="font-mono text-xs uppercase tracking-[0.12em]">
          {crumbs.map((crumb, i) => {
            const last = i === crumbs.length - 1;
            return (
              <BreadcrumbItem key={`${crumb.label}-${i}`}>
                {crumb.to && !last ? (
                  <BreadcrumbLink render={<Link to={crumb.to} />}>{crumb.label}</BreadcrumbLink>
                ) : last ? (
                  <BreadcrumbPage className="text-white/90">{crumb.label}</BreadcrumbPage>
                ) : (
                  <span className={crumb.accent ? "text-primary/80" : "text-white/45"}>
                    {crumb.label}
                  </span>
                )}
                {!last && <BreadcrumbSeparator />}
              </BreadcrumbItem>
            );
          })}
        </BreadcrumbList>
      </Breadcrumb>
      <span className="ml-auto flex shrink-0 items-center gap-1.5">
        {config?.version && (
          <span className="flex shrink-0 items-center gap-1.5">
          <span
            className="font-mono text-[11px] tracking-[0.08em] text-white/35 tabular-nums"
            title="Mosaera engine version"
          >
            v{config.version}
          </span>
          {/* Maturity channel (ADR-0088) — the separate how-much-to-trust-it axis. Hidden at
              `stable`, where the absence of a channel IS the signal and the badge would be noise. */}
          {config.maturity && config.maturity !== "stable" && (
            <Badge
              variant="outline"
              className="h-4 px-1.5 py-0 font-mono text-[10px] tracking-[0.1em] text-muted-foreground/70 uppercase"
              title={`Pre-release channel — ${config.maturity}. Not production-authorized until v1.0 (ADR-0088).`}
            >
              {config.maturity}
            </Badge>
            )}
          </span>
        )}
        {/* Wired 2026-08-22 (it was a deliberate handler-less placeholder). Per project, and it
            shares the Overview band's query, so opening it costs no extra request. */}
        <NotificationsBell projectId={bellProjectId} />
      </span>
    </header>
  );
}
