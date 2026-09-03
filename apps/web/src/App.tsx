import { Navigate, Route, Routes } from "react-router-dom";

import appBackground from "./assets/app-background.webp";

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

import { AppHeader } from "./components/AppHeader";
import { SetupBanner } from "./components/setup/SetupBanner";
import { AppSidebar } from "./components/AppSidebar";
import { NotFoundPage } from "./pages/NotFoundPage";
import { NewProjectPage } from "./pages/NewProjectPage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunPage } from "./pages/RunPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SubmitPage } from "./pages/SubmitPage";

export function App() {
  // The sidebar persists its state in a cookie; honor it on first paint.
  const defaultOpen = !document.cookie.includes("sidebar_state=false");
  return (
    <SidebarProvider defaultOpen={defaultOpen}>
      {/* The canvas: ONE image under the whole shell + one flat black scrim — no vignette, no
          gradient, no per-region layers (a rail-pinned crop was tried and retired 2026-08-13:
          it duplicated its figure against the full canvas and overflowed the collapsed rail).
          app-background.webp is the owner-picked great-library hall (2026-08-13), already
          engraved dark — so one /95 scrim, matching the shell — one darkness everywhere.
          pointer-events-none so it can never eat a click. */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: `url(${appBackground})` }}
        />
        <div className="absolute inset-0 bg-black/95" />
      </div>
      <AppSidebar />
      <SidebarInset className="bg-transparent">
        {/* Deferred setup stays visible until it is actually done (#119) — derived from the
            live check, so it clears itself with no client action. */}
        <SetupBanner />
        <AppHeader />
        {/* Full application window: no max-width cap on content. The gutter is TRANSPARENT
            (coherence pass, owner-approved hybrid): the canvas breathes between opaque cards;
            under the /95 scrim it reads within a hair of --background, so contrast holds. */}
        <main className="min-w-0 flex-1 overflow-x-clip px-6 pb-16 pt-6 lg:px-8">
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/projects/new" element={<NewProjectPage />} />
            <Route path="/projects/:id" element={<Navigate to="overview" replace />} />
            {/* Project-nested run views keep the project shell (sidebar group +
                breadcrumb) because AppSidebar/AppHeader match /projects/:id/*. */}
            <Route path="/projects/:id/runs/:runId" element={<RunPage />} />
            {/* Optional trailing :slug is a cosmetic commit-style tail; the id resolves the run. */}
            <Route path="/projects/:id/history/:runId/:slug?" element={<RunDetailPage />} />
            <Route path="/projects/:id/:section" element={<ProjectDetailPage />} />
            <Route path="/run" element={<SubmitPage />} />
            {/* Global fallback for ad-hoc runs with no project. */}
            <Route path="/runs/:id" element={<RunPage />} />
            {/* Ad-hoc (project-less) run detail. The global history LIST was
                removed — runs live under their project now. */}
            <Route path="/history/:id/:slug?" element={<RunDetailPage />} />
            <Route path="/settings" element={<Navigate to="/settings/general" replace />} />
            <Route path="/settings/:section" element={<SettingsPage />} />
            {/* The Git section has a detail level: /settings/git is the provider index,
                /settings/git/:provider the panel. Deep-linkable so the delivery CTAs and the
                OAuth callback can land on the exact page that fixes the thing. */}
            <Route path="/settings/:section/:provider" element={<SettingsPage />} />
            {/* Catch-all (5E): an unknown path used to render a silent black page
                (live-confirmed at /projects) — App had no fallback route at all. */}
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
