import { useSearchParams } from "react-router-dom";

import type { ActiveRun, Project } from "../../api/client";
import { ActivityWorkspace } from "../activity/ActivityWorkspace";
import { ViewSwitcher } from "../ViewSwitcher";
import { RunsWorkspace } from "./RunsWorkspace";

const VIEWS = [
  { id: "runs", label: "Runs" },
  { id: "activity", label: "Event log" },
] as const;
type View = (typeof VIEWS)[number]["id"];

function isView(v: string | null): v is View {
  return v === "runs" || v === "activity";
}

/** Runs section (Phase 9 product simplification): Activity used to be its own tab describing
 *  itself as complementing Runs — one card per run there, every gate decision/node step/MR
 *  event as its own row here, over the SAME stream. Now it is a view toggle on Runs instead of
 *  a second sidebar entry, mounting the unmodified `ActivityWorkspace`. The retired `/activity`
 *  route redirects here with `?view=activity` (`ProjectDetailPage`). */
export function RunsSection({
  project,
  activeRun,
}: {
  project: Project;
  activeRun?: ActiveRun;
}) {
  const [params, setParams] = useSearchParams();
  const requested = params.get("view");
  const view: View = isView(requested) ? requested : "runs";

  function setView(next: View) {
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next === "runs") p.delete("view");
        else p.set("view", next);
        return p;
      },
      { replace: true },
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <ViewSwitcher label="Runs view" value={view} options={VIEWS} onChange={setView} />
      <div className="min-h-0 flex-1">
        {view === "activity" ? (
          <ActivityWorkspace project={project} />
        ) : (
          <RunsWorkspace project={project} activeRun={activeRun} />
        )}
      </div>
    </div>
  );
}
