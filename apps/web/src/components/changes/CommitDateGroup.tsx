import type { BacklogItem } from "../../api/client";
import type { ItemGroup } from "../../lib/itemRuns";
import { ConsoleLabel } from "../overview/bits";
import { ItemChangeGroup } from "./ItemChangeGroup";

/** One calendar-day bucket of the changes list: a sticky date label over its
 *  item rows (an item sits in the bucket of its LATEST attempt). Sticks within
 *  the list's internal scroll container. */
export function CommitDateGroup({
  label,
  groups,
  backlog,
}: {
  label: string;
  groups: ItemGroup[];
  backlog: BacklogItem[];
}) {
  return (
    <section className="flex flex-col">
      <div className="sticky top-0 z-10 border-b border-border/50 bg-background/90 pb-1.5 pt-1 backdrop-blur-sm">
        <ConsoleLabel>{label}</ConsoleLabel>
      </div>
      <div className="flex flex-col">
        {groups.map((g) => (
          <ItemChangeGroup
            key={g.item ? `item-${g.item.id}` : `run-${g.latest.id}`}
            group={g}
            backlog={backlog}
          />
        ))}
      </div>
    </section>
  );
}
