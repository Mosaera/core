import { useSearchParams } from "react-router-dom";

import type { Project } from "../../api/client";
import { ArtifactsWorkspace } from "../artifacts/ArtifactsWorkspace";
import { ChangesCommitList } from "../changes/ChangesCommitList";
import { ViewSwitcher } from "../ViewSwitcher";
import { DeliveryWorkspace } from "./DeliveryWorkspace";

const VIEWS = [
  { id: "delivery", label: "Delivery" },
  { id: "changes", label: "Review changes" },
  { id: "artifacts", label: "Files & artifacts" },
] as const;
type View = (typeof VIEWS)[number]["id"];

function isView(v: string | null): v is View {
  return v === "delivery" || v === "changes" || v === "artifacts";
}

/** Delivery section (Phase 9 product simplification): Changes / Delivery / Artifacts used to
 *  be three tabs over one git delta — review, manage, take away. They still are exactly that,
 *  just as an internal view switch over the SAME three unmodified workspaces instead of three
 *  sidebar entries. The retired `/changes` and `/artifacts` routes redirect here with
 *  `?view=changes` / `?view=artifacts` (`ProjectDetailPage`), so every deep link and bookmark
 *  keeps landing on the right view. */
export function DeliverySection({ project }: { project: Project }) {
  const [params, setParams] = useSearchParams();
  const requested = params.get("view");
  const view: View = isView(requested) ? requested : "delivery";

  function setView(next: View) {
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next === "delivery") p.delete("view");
        else p.set("view", next);
        return p;
      },
      { replace: true },
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <ViewSwitcher label="Delivery view" value={view} options={VIEWS} onChange={setView} />
      <div className="min-h-0 flex-1">
        {view === "changes" && <ChangesCommitList project={project} />}
        {view === "artifacts" && <ArtifactsWorkspace project={project} />}
        {view === "delivery" && <DeliveryWorkspace project={project} />}
      </div>
    </div>
  );
}
