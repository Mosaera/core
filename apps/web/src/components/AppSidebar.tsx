import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  Clock,
  FolderKanban,
  GitMerge,
  GitPullRequest,
  LayoutDashboard,
  ListTodo,
  MessagesSquare,
  Package,
  Play,
  Rocket,
  Settings,
  SlidersHorizontal,
} from "lucide-react";
import { NavLink, useLocation, useMatch } from "react-router-dom";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";

import { api } from "../api/client";
import { isInitializing } from "../lib/overview";

/** Collapse/expand control mounted on the sidebar's right edge (desktop only —
 *  on mobile the drawer is opened from the header and dismissed by nav/backdrop).
 *  Subtle amber console control straddling the border, centered in the h-12 band. */
function SidebarEdgeTrigger() {
  const { state, toggleSidebar } = useSidebar();
  const expanded = state === "expanded";
  const label = expanded ? "Collapse sidebar" : "Expand sidebar";
  return (
    <button
      type="button"
      data-slot="sidebar-edge-trigger"
      aria-label={label}
      title={`${label} (Ctrl+B)`}
      onClick={toggleSidebar}
      // Anchored at the bottom edge in BOTH states, so it never moves on
      // collapse/expand and never competes with the logo at the rail top.
      className="absolute bottom-[13px] -right-[11px] z-30 hidden size-[22px] items-center justify-center rounded-full border border-primary/40 bg-sidebar text-primary shadow-sm transition-colors hover:border-primary/70 hover:bg-primary/15 focus-visible:ring-2 focus-visible:ring-ring md:flex"
    >
      {expanded ? <ChevronLeft className="size-3.5" /> : <ChevronRight className="size-3.5" />}
    </button>
  );
}

/* Glass nav states (owner, 2026-08-13): the vendored button paints its hover/active pill with
   the opaque gray `--sidebar-accent` token; these classes displace it per variant bucket with
   the login's white-alpha fills, and the active hairline is an INSET shadow so nothing shifts.
   Do not swap the token instead — `hover:bg-sidebar-accent/50` color-mixes it to half alpha. */
const NAV_GLASS =
  "hover:bg-white/6 active:bg-white/10 data-active:bg-white/10 data-active:hover:bg-white/10";

const GLOBAL_NAV = [
  { to: "/", end: true, label: "Projects", icon: FolderKanban },
  { to: "/run", end: false, label: "New run", icon: Play },
];

// Shown only during the initialize phase (before the backlog is built).
const START_SECTIONS = [
  { slug: "start", label: "Start", icon: Rocket },
  { slug: "settings", label: "Settings", icon: SlidersHorizontal },
];

const PROJECT_SECTIONS = [
  { slug: "overview", label: "Overview", icon: LayoutDashboard },
  { slug: "pm", label: "PM", icon: MessagesSquare },
  { slug: "backlog", label: "Backlog", icon: ListTodo },
  { slug: "changes", label: "Changes", icon: GitPullRequest },
  { slug: "delivery", label: "Delivery", icon: GitMerge },
  { slug: "artifacts", label: "Artifacts", icon: Package },
  { slug: "runs", label: "Runs", icon: Activity },
  { slug: "activity", label: "Activity", icon: Clock },
  // Sliders, not the gear — the footer's global Settings owns the gear.
  { slug: "settings", label: "Settings", icon: SlidersHorizontal },
];

/** App-wide left rail: global console nav, plus the current project's sections
 *  when a project is open. Collapses to an icon rail (Ctrl/Cmd+B). */
export function AppSidebar() {
  const location = useLocation();
  const { isMobile, setOpenMobile } = useSidebar();
  // useMatch ignores route ranking, so exclude the static /projects/new page.
  const match = useMatch("/projects/:id/*");
  const activeProjectId =
    match && match.params.id !== "new" ? (match.params.id ?? null) : null;
  // Section highlight only applies when we're actually inside the project route.
  const currentSection = activeProjectId
    ? match?.params["*"]?.split("/")[0] || "overview"
    : null;

  // Remember the last-opened project so its section group stays in the rail while
  // you're on the global Settings page — switching to app settings shouldn't drop
  // your project context. Persisted so it also survives a reload on /settings.
  const [lastProjectId, setLastProjectId] = useState<string | null>(() =>
    localStorage.getItem("mosaera:last-project"),
  );
  useEffect(() => {
    if (activeProjectId && activeProjectId !== lastProjectId) {
      setLastProjectId(activeProjectId);
      localStorage.setItem("mosaera:last-project", activeProjectId);
    }
  }, [activeProjectId, lastProjectId]);

  // Keep the project group ONLY on the global Settings page — Projects and New-run
  // intentionally show no project group.
  const onGlobalSettings = location.pathname.startsWith("/settings");
  const projectId = activeProjectId ?? (onGlobalSettings ? lastProjectId : null);

  // On mobile the sheet must dismiss as soon as a destination is picked.
  function closeMobile() {
    if (isMobile) setOpenMobile(false);
  }

  // Shares the detail page's cache entry — no extra polling, name + backlog ride along.
  const { data: project, isError } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId as string),
    enabled: projectId !== null,
  });
  // If the remembered project was deleted, stop resurrecting it in the rail.
  useEffect(() => {
    if (isError && !activeProjectId) {
      setLastProjectId(null);
      localStorage.removeItem("mosaera:last-project");
    }
  }, [isError, activeProjectId]);
  const backlog = project?.backlog ?? [];
  const backlogDone = backlog.filter(
    (i) => i.status === "in_review" || i.status === "done",
  ).length;
  // Before the backlog is built, the project shows only Start (+ Settings).
  const sections =
    project && isInitializing(project.status) ? START_SECTIONS : PROJECT_SECTIONS;

  function isGlobalActive(to: string, end: boolean): boolean {
    return end ? location.pathname === to : location.pathname.startsWith(to);
  }

  return (
    /* Login-glass rail (shell pass 1b). The className lands on the fixed desktop container:
       black/20 + 4px blur over the canvas image, a white/12 hairline on the content edge, and
       the login's one deep shadow. `--sidebar: transparent` clears the inner opaque fill so the
       glass shows through; `--sidebar-border` follows the hairline so the h-12 header divider
       and every internal rule match the AppHeader's without touching ui/sidebar.tsx. The mobile
       sheet is styled separately in index.css — it floats over content and needs a heavier
       surface to stay readable. */
    <Sidebar
      collapsible="icon"
      className="nav-rail-canvas border-white/12 shadow-[0_16px_50px_rgba(0,0,0,0.28)] [--sidebar-border:rgba(255,255,255,0.12)] [--sidebar:transparent]"
    >
      {/* h-12 + bottom border continues the AppHeader's border across the rail,
          so the top-left corner reads as one deliberate band. */}
      <SidebarHeader className="h-12 justify-center border-b border-sidebar-border">
        <div className="flex h-8 items-center gap-2.5 px-0.5 font-sans group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
          <span
            aria-hidden
            className="flex size-8 shrink-0 select-none items-center justify-center rounded-md bg-primary font-sans text-[19px] font-extrabold leading-none tracking-tight text-primary-foreground"
          >
            Æ
          </span>
          <span className="truncate text-sm font-extrabold uppercase tracking-[0.14em] group-data-[collapsible=icon]:hidden">
            MOS<span className="text-primary">Æ</span>RA
          </span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Console</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {GLOBAL_NAV.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton
                    className={NAV_GLASS}
                    isActive={isGlobalActive(item.to, item.end)}
                    tooltip={item.label}
                    render={<NavLink to={item.to} end={item.end} onClick={closeMobile} />}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        {projectId && (
          <SidebarGroup>
            <SidebarGroupLabel className="truncate" title={project?.name ?? projectId}>
              {project?.name ?? projectId}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {sections.map((s) => (
                  <SidebarMenuItem key={s.slug}>
                    <SidebarMenuButton
                      className={NAV_GLASS}
                      isActive={currentSection === s.slug}
                      tooltip={s.label}
                      render={
                        <NavLink to={`/projects/${projectId}/${s.slug}`} end onClick={closeMobile} />
                      }
                    >
                      <s.icon />
                      <span>{s.label}</span>
                    </SidebarMenuButton>
                    {s.slug === "backlog" && backlog.length > 0 && (
                      <SidebarMenuBadge className="font-mono">
                        {backlogDone}/{backlog.length}
                      </SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>
      <SidebarFooter>
        {/* Global settings live at the rail's base, beside the collapse control. */}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              className={NAV_GLASS}
              isActive={isGlobalActive("/settings", false)}
              tooltip="Settings"
              render={<NavLink to="/settings" onClick={closeMobile} />}
            >
              <Settings />
              <span>Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <div className="px-1 pb-1 font-mono text-[10px] uppercase tracking-[0.2em] text-sidebar-foreground/40 group-data-[collapsible=icon]:hidden">
          governed execution
        </div>
      </SidebarFooter>
      <SidebarRail />
      <SidebarEdgeTrigger />
    </Sidebar>
  );
}
