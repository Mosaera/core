import { LogOut } from "lucide-react";
import { NavLink, Navigate, useParams } from "react-router-dom";

import { cn } from "@/lib/utils";

import { useAuth } from "../api/authContext";
import { AdvancedSettings } from "../components/settings/AdvancedSettings";
import { AutonomySettings } from "../components/settings/AutonomySettings";
import { BehaviorSettings } from "../components/settings/BehaviorSettings";
import { GeneralSettings } from "../components/settings/GeneralSettings";
import { GitIndex } from "../components/settings/git/GitIndex";
import { GitLabPanel } from "../components/settings/git/GitLabPanel";
import { GitHubPanel } from "../components/settings/git/GitHubPanel";
import { ModelsSettings } from "../components/settings/models/ModelsSettings";
import { SettingsCard } from "../components/settings/SettingsCard";
import { UsersCard } from "../components/settings/UsersCard";

type Section = { slug: string; label: string; need: "read" | "config" | "admin" };

// Order: intent first (Behavior), then the mechanics it derives (General → Autonomy → Advanced), then the
// resource/account sections (Models → Git → Users, admin last).
// `read` = everyone may SEE it; the section itself renders read-only for a member (KnobForm
// already does this via editable={isAdmin} + "Read-only — admins can edit these"). Every one of
// these GETs is auth-only server-side, so hiding them denied members sight of configuration the
// API would have served them.
//
// Models and Git stay `config` (admin-only) NOT because the server refuses the read, but
// because their write controls carry no role awareness — exposing them to a member today would
// hand out Save buttons that 403. Gating those controls is its own pass; shipping the dead-end
// would trade one honesty defect for another.
const SECTIONS: Section[] = [
  // Behavior first: it states INTENT, and the sections after it are the mechanics that intent
  // derives (ADR-0122). Reading the page top-down is then the same order as deciding.
  { slug: "behavior", label: "Behavior", need: "read" },
  { slug: "general", label: "General", need: "read" },
  { slug: "autonomy", label: "Autonomy", need: "read" },
  { slug: "advanced", label: "Advanced", need: "read" },
  { slug: "models", label: "Models", need: "config" },
  { slug: "git", label: "Git", need: "config" },
  { slug: "users", label: "Users", need: "admin" },
];

// `provider` is the second path segment of /settings/git/:provider — the Git section is the
// one section with a detail level below it, because a forge connection has enough state
// (app registration, installations, per-project credentials) to be its own page rather than
// a card among cards.
function sectionBody(slug: string, provider?: string) {
  switch (slug) {
    case "general":
      return <GeneralSettings />;
    case "models":
      return <ModelsSettings />;
    case "git":
      if (provider === "github") return <GitHubPanel />;
      // GitLab: the first-run wizard when no OAuth app is registered, otherwise its existing
      // card unchanged, both inside the shared provider shell.
      if (provider === "gitlab") return <GitLabPanel />;
      return <GitIndex />;
    case "users":
      return <UsersCard />;
    case "behavior":
      return <BehaviorSettings />;
    case "autonomy":
      return <AutonomySettings />;
    case "advanced":
      return <AdvancedSettings />;
    default:
      return null;
  }
}

/** The Settings area — a left section rail (deep-linkable `/settings/:section`) + a
 *  detail pane, in the enterprise settings idiom. Config sections need admin on an
 *  authenticated instance (an open loopback dev box keeps them usable); Users needs
 *  admin. A member with no config access sees a notice + sign-out. */
export function SettingsPage() {
  const { section = "general", provider } = useParams();
  const { user, isAdmin, status, logout } = useAuth();
  const canConfig = isAdmin || !status?.auth_required;

  const visible = SECTIONS.filter((s) =>
    s.need === "admin" ? isAdmin : s.need === "read" ? true : canConfig,
  );

  const SignOut = () =>
    user ? (
      <button
        onClick={() => void logout()}
        className="flex items-center gap-1.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground"
      >
        <LogOut className="size-3.5" /> Sign out
      </button>
    ) : null;

  if (visible.length === 0) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
        <SettingsCard>
          <p className="text-sm text-muted-foreground">Settings are managed by an administrator.</p>
        </SettingsCard>
        {user && (
          <SettingsCard>
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm">
                Signed in as <span className="text-foreground/80">{user.username}</span>
              </span>
              <SignOut />
            </div>
          </SettingsCard>
        )}
      </div>
    );
  }

  const active = visible.find((s) => s.slug === section);
  if (!active) return <Navigate to={`/settings/${visible[0].slug}`} replace />;

  return (
    <div className="flex w-full items-start gap-8">
      <nav
        aria-label="Settings sections"
        className="sticky top-[72px] flex w-44 shrink-0 flex-col items-stretch gap-0.5 self-start"
      >
        <h1 className="mb-2 px-2 text-lg font-semibold tracking-tight">Settings</h1>
        {visible.map((s) => (
          <NavLink
            key={s.slug}
            to={`/settings/${s.slug}`}
            className={({ isActive }) =>
              cn(
                "rounded-md px-2 py-1.5 text-sm transition-colors",
                isActive
                  ? "bg-primary/15 font-medium text-primary"
                  : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
              )
            }
          >
            {s.label}
          </NavLink>
        ))}
        {user && (
          <>
            <div className="my-2 h-px bg-border/50" />
            <SignOut />
          </>
        )}
      </nav>

      <div className="min-w-0 flex-1">{sectionBody(active.slug, provider)}</div>
    </div>
  );
}
