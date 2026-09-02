"""Backlog item CRUD, ordering, dependency graph, soft-lock, and structural ops."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaera_memory.models import BacklogItem
from mosaera_memory.store._base import _DELIVERED, StoreBase, _backlog_summary

# What a clarification's proposals ARE, and therefore what the operator may do with them
# (ADR-0091). Declared as a frozenset so adding one is a deliberate act, like CLAIM_PROVENANCES.
#   acceptance  each proposal is the COMPLETE replacement acceptance text — the intake contract
#               (the PM prompt states it; intake_ask passes an `enhance` op's acceptance). These
#               may be accepted by index: one click rewrites the bar.
#   direction   each proposal is guidance for a HUMAN ("amend the criteria so tests/x.py can
#               pass"). Never acceptance text, never one-click — the operator must author the
#               replacement themselves, or say the bar stands.
PROPOSAL_KINDS = frozenset({"acceptance", "direction"})

# How a clarification ended. `affirmed` is the operator position the card had no representation
# for: *the bar is right, the CODE is wrong, try again* — distinct from `dismissed` ("not now"),
# which is what it used to collapse into.
CLARIFICATION_STATUSES = frozenset({"resolved", "dismissed", "affirmed"})


class BacklogMixin(StoreBase):
    def add_backlog_item(
        self,
        project_id: str,
        title: str,
        description: str = "",
        acceptance: str = "",
        position: int = 0,
    ) -> int:
        with self.session() as s, s.begin():
            item = BacklogItem(
                project_id=project_id,
                title=title,
                description=description,
                acceptance=acceptance,
                position=position,
            )
            s.add(item)
            s.flush()
            return item.id

    def list_backlog_items(self, project_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(BacklogItem)
            .where(BacklogItem.project_id == project_id)
            .order_by(BacklogItem.position, BacklogItem.id)
        )
        with self.session() as s:
            return [_backlog_summary(i) for i in s.scalars(stmt)]

    def get_backlog_item(self, item_id: int) -> dict[str, Any] | None:
        with self.session() as s:
            item = s.get(BacklogItem, item_id)
            return _backlog_summary(item) if item is not None else None

    def update_backlog_item(
        self,
        item_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        acceptance: str | None = None,
        status: str | None = None,
        design: str | None = None,
        design_key: str | None = None,
        branch: str | None = None,
        mr_url: str | None = None,
        mr_state: str | None = None,
        mr_target: str | None = None,
    ) -> None:
        with self.session() as s, s.begin():
            item = s.get(BacklogItem, item_id)
            if item is None:
                return
            if title is not None:
                item.title = title
            if description is not None:
                item.description = description
            if acceptance is not None:
                item.acceptance = acceptance
            if status is not None:
                item.status = status
            if design is not None:
                item.design = design
            if design_key is not None:
                item.design_key = design_key
            if branch is not None:
                item.branch = branch
            if mr_url is not None:
                item.mr_url = mr_url
            if mr_state is not None:
                item.mr_state = mr_state
            if mr_target is not None:
                item.mr_target = mr_target

    def set_item_dependencies(self, item_id: int, depends_on_ids: list[int]) -> None:
        """Replace an item's dependency edges. Validates: each dep exists in the SAME
        project, no self-dependency, and no cycle. Raises ValueError on invalid input."""
        wanted = list(dict.fromkeys(depends_on_ids))  # dedupe, keep order
        with self.session() as s, s.begin():
            item = s.get(BacklogItem, item_id)
            if item is None:
                raise ValueError("unknown item")
            if item_id in wanted:
                raise ValueError("an item cannot depend on itself")
            deps: list[BacklogItem] = []
            for dep_id in wanted:
                dep = s.get(BacklogItem, dep_id)
                if dep is None or dep.project_id != item.project_id:
                    raise ValueError(f"unknown dependency in this project: {dep_id}")
                deps.append(dep)
            if self._would_cycle(s, item_id, wanted):
                raise ValueError("dependency cycle detected")
            item.depends_on = deps

    @staticmethod
    def _would_cycle(s: Session, item_id: int, wanted_dep_ids: list[int]) -> bool:
        """Would adding item_id -> each wanted dep close a cycle? True iff item_id is
        reachable from any wanted dep by following EXISTING depends_on edges."""
        stack = list(wanted_dep_ids)
        seen: set[int] = set()
        while stack:
            cur = stack.pop()
            if cur == item_id:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            dep = s.get(BacklogItem, cur)
            if dep is not None:
                stack.extend(d.id for d in dep.depends_on)
        return False

    def blocking_dependencies(self, item_id: int) -> list[int]:
        """Dependency item ids not yet delivered — the item can't run until this is
        empty. Authoritative check for the launch gate (recomputed, not from a stale dict)."""
        with self.session() as s:
            item = s.get(BacklogItem, item_id)
            if item is None:
                return []
            return sorted(d.id for d in item.depends_on if d.status not in _DELIVERED)

    def reorder_backlog(self, project_id: str, ordered_ids: list[int]) -> None:
        """Rewrite backlog positions to match ``ordered_ids`` (0..n-1) in one transaction,
        so positions stay unique. ``ordered_ids`` must be exactly the project's item ids
        (a complete reordering); raises ValueError otherwise."""
        wanted = list(dict.fromkeys(ordered_ids))
        with self.session() as s, s.begin():
            items = (
                s.execute(select(BacklogItem).where(BacklogItem.project_id == project_id))
                .scalars()
                .all()
            )
            by_id = {it.id: it for it in items}
            if set(wanted) != set(by_id):
                raise ValueError("reorder must list exactly the project's item ids")
            for pos, item_id in enumerate(wanted):
                by_id[item_id].position = pos

    def set_item_lock(self, item_id: int, locked: bool, reason: str = "") -> None:
        """Soft-lock (or unlock) an item. When locked, ``reason`` is the caveat shown to
        the user (who can override). Unlocking clears the reason."""
        with self.session() as s, s.begin():
            item = s.get(BacklogItem, item_id)
            if item is None:
                return
            item.locked = bool(locked)
            item.lock_reason = reason if locked else ""

    def is_item_locked(self, item_id: int) -> tuple[bool, str]:
        """(locked, reason) for the launch gate — recomputed, authoritative."""
        with self.session() as s:
            item = s.get(BacklogItem, item_id)
            if item is None:
                return (False, "")
            return (bool(item.locked), item.lock_reason)

    def set_item_clarification(
        self,
        item_id: int,
        *,
        claim_text: str,
        why_unbindable: str,
        proposals: list[str],
        axis: str,
        proposal_kind: str,
    ) -> None:
        """Record the OPEN clarification request on an item (ADR-0080 §1, ADR-0091).

        Validated BEFORE the session opens (the offline-testable boundary): a request with no
        proposals or empty texts is rejected — a request must always offer the operator
        something. One request per item; a new request replaces an unresolved one (the batching
        rule — never a queue of nags). Fields clamped like the charter parse.

        ``proposal_kind`` is REQUIRED and has NO DEFAULT, which is the whole mechanism. This
        channel has one consumer (``resolve_clarification``) that writes an accepted proposal
        into ``acceptance`` verbatim, and three producers that disagreed about whether a proposal
        IS acceptance text. The ESCALATE arm writes *directions for a human* — "amend the criteria
        so tests/x.py can pass" — and one click made that sentence the item's bar. A default here
        would silently readmit that the moment a fourth producer forgets; a required argument
        makes forgetting a TypeError at the boundary.

        ``axis`` reuses the intake vocabulary (``mosaera_core.intake_ask``: checkability /
        decidability / reachability, ADR-0089) rather than minting a parallel enum.
        """
        claim_text = str(claim_text or "").strip()[:2000]
        why = str(why_unbindable or "").strip()[:2000]
        props = [str(x).strip()[:2000] for x in (proposals or []) if str(x).strip()][:3]
        if not claim_text:
            raise ValueError("clarification: empty claim_text")
        if not props:
            raise ValueError("clarification: at least one proposal is required")
        if proposal_kind not in PROPOSAL_KINDS:
            raise ValueError(f"clarification: unknown proposal_kind {proposal_kind!r}")
        if not str(axis or "").strip():
            raise ValueError("clarification: empty axis")
        from datetime import UTC, datetime

        with self.session() as s, s.begin():
            item = s.get(BacklogItem, item_id)
            if item is None:
                raise ValueError(f"clarification: unknown item {item_id}")
            item.clarification = {
                "claim_text": claim_text,
                "why_unbindable": why,
                "proposals": props,
                "axis": str(axis).strip()[:64],
                "proposal_kind": proposal_kind,
                "status": "open",
                "asked_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }

    def resolve_item_clarification(
        self, item_id: int, *, status: str = "resolved", resolution: str = ""
    ) -> None:
        """Close the open request, RETAINING the exchange (#63 ledger): the ask keeps its
        fields and gains `status` (resolved|dismissed|affirmed), the operator's `resolution`
        text, and `resolved_at`. The answer's ACCEPTANCE effect still travels the validated
        `enhance` path — this records the exchange, it does not apply it. A later ask
        replaces the record wholesale (set_item_clarification — the batching rule).

        `affirmed` (ADR-0091) means the operator said the bar STANDS. It is recorded rather than
        merely cleared because the ESCALATE arm re-fires on the next sweep: without a record the
        same question returns, and an operator nagged by an unanswerable question eventually
        lowers the bar to make it stop."""
        if status not in CLARIFICATION_STATUSES:
            raise ValueError(f"clarification: unknown status {status!r}")
        from datetime import UTC, datetime

        with self.session() as s, s.begin():
            item = s.get(BacklogItem, item_id)
            if item is None or not isinstance(item.clarification, dict):
                return
            item.clarification = {
                **item.clarification,
                "status": status,
                "resolution": str(resolution or "").strip()[:2000],
                "resolved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }

    def item_clarification(self, item_id: int) -> dict | None:
        """The open request, or None — recomputed for the launch gate (authoritative)."""
        with self.session() as s:
            item = s.get(BacklogItem, item_id)
            if item is None or not isinstance(item.clarification, dict):
                return None
            return dict(item.clarification) if item.clarification.get("status") == "open" else None

    @staticmethod
    def _renumber(s: Session, project_id: str) -> None:
        """Renumber a project's backlog positions to 0..n-1 by (position, id) — keeps them
        unique and gap-free after a structural change. Runs inside the caller's transaction."""
        items = (
            s.execute(
                select(BacklogItem)
                .where(BacklogItem.project_id == project_id)
                .order_by(BacklogItem.position, BacklogItem.id)
            )
            .scalars()
            .all()
        )
        for pos, it in enumerate(items):
            it.position = pos

    @staticmethod
    def _refuse_if_mr_live(item: BacklogItem, verb: str) -> None:
        """A backlog row is the ONLY record of what its merge request targets (0028) and which
        branch it sources from; branch protection reads it. Any operation that DELETES the row
        silently unprotects those branches and orphans a live MR.

        The delete path grew this guard first (red-team 2026-08-18, finding 5), but split and
        merge delete rows too — both reachable from an LLM-proposed curation changeset an
        operator accepts — so they were two unguarded doors to the same orphaning. "closed" is
        not terminal: GitLab reopens merge requests.
        """
        if item.mr_url and item.mr_state not in ("merged", ""):
            raise ValueError(
                f"cannot {verb} an item while its merge request is open — "
                "merge it, or close it from the Delivery page, first"
            )

    def delete_backlog_item(self, item_id: int) -> None:
        """Delete one backlog item. CASCADE removes its dependency edges in BOTH directions
        (its own deps and the edges where others depend on it — dependents simply lose a
        blocker, which can't create a cycle); a Run's item_id is SET NULL (history kept,
        unlinked). Survivors are renumbered. No-op if gone; refuses while a run is live."""
        with self.session() as s, s.begin():
            item = s.get(BacklogItem, item_id)
            if item is None:
                return
            if item.status == "in_progress":
                raise ValueError("cannot delete an item while its run is in progress")
            self._refuse_if_mr_live(item, "delete")
            pid = item.project_id
            s.delete(item)
            s.flush()
            self._renumber(s, pid)

    def split_backlog_item(self, item_id: int, parts: list[dict[str, str]]) -> list[int]:
        """Replace one item with N children. Each child inherits the parent's dependencies;
        every item that depended on the parent is rewired to depend on ALL children (a
        dependent waits for every piece). The parent is deleted. Returns the new child ids.
        Raises ValueError on an unknown item, empty parts, or a cycle."""
        if not parts:
            raise ValueError("split needs at least one part")
        with self.session() as s, s.begin():
            parent = s.get(BacklogItem, item_id)
            if parent is None:
                raise ValueError("unknown item")
            self._refuse_if_mr_live(parent, "split")  # the parent row is DELETED below
            pid = parent.project_id
            parent_deps = list(parent.depends_on)
            dependents = list(parent.dependents)
            children: list[BacklogItem] = []
            for p in parts:
                title = str(p.get("title", "")).strip()[:512]
                if not title:
                    raise ValueError("each split part needs a title")
                child = BacklogItem(
                    project_id=pid,
                    title=title,
                    description=str(p.get("description", "")),
                    acceptance=str(p.get("acceptance", "")),
                    position=parent.position,  # renumber places them in the parent's slot
                )
                child.depends_on = list(parent_deps)
                s.add(child)
                children.append(child)
            s.flush()  # children now have ids
            for x in dependents:
                new_deps = [d for d in x.depends_on if d.id != parent.id]
                probe = [d.id for d in new_deps]
                for child in children:
                    if self._would_cycle(s, x.id, [*probe, child.id]):
                        raise ValueError("split would create a dependency cycle")
                    new_deps.append(child)
                    probe.append(child.id)
                x.depends_on = new_deps
            s.delete(parent)
            s.flush()
            self._renumber(s, pid)
            return [c.id for c in children]

    def merge_backlog_items(
        self,
        target_id: int,
        source_ids: list[int],
        *,
        title: str | None = None,
        description: str | None = None,
        acceptance: str | None = None,
    ) -> None:
        """Fold ``source_ids`` into ``target_id``: union their dependencies onto the target,
        repoint everything that depended on a source to depend on the target, then delete the
        sources. Optionally overwrite the target's title/description/acceptance with merged
        text. Same-project only; cycle-guarded; duplicate edges avoided."""
        with self.session() as s, s.begin():
            target = s.get(BacklogItem, target_id)
            if target is None:
                raise ValueError("unknown target")
            src_ids = [i for i in dict.fromkeys(source_ids) if i != target_id]
            if not src_ids:
                raise ValueError("merge needs at least one source distinct from the target")
            fetched = [s.get(BacklogItem, i) for i in src_ids]
            if any(x is None or x.project_id != target.project_id for x in fetched):
                raise ValueError("unknown or cross-project source")
            for src in fetched:
                if src is not None:
                    self._refuse_if_mr_live(src, "merge")  # every source row is DELETED below
            sources = [x for x in fetched if x is not None]  # all non-None per the check
            pid = target.project_id
            dead = set(src_ids) | {target_id}
            # 1. union outgoing deps onto target (exclude self + sources), distinct.
            merged: dict[int, BacklogItem] = {
                d.id: d for d in target.depends_on if d.id not in dead
            }
            for x in sources:
                for d in x.depends_on:
                    if d.id not in dead:
                        merged.setdefault(d.id, d)
            want = list(merged.values())
            if self._would_cycle(s, target_id, [d.id for d in want]):
                raise ValueError("merge would create a dependency cycle")
            target.depends_on = want
            # 2. repoint each source's dependents onto the target (distinct; cycle-guarded).
            for x in sources:
                for dep_of_src in list(x.dependents):
                    if dep_of_src.id in dead:
                        continue
                    new_deps = [d for d in dep_of_src.depends_on if d.id not in dead]
                    if all(d.id != target_id for d in new_deps):
                        probe = [d.id for d in new_deps]
                        if self._would_cycle(s, dep_of_src.id, [*probe, target_id]):
                            raise ValueError("merge would create a dependency cycle")
                        new_deps.append(target)
                    dep_of_src.depends_on = new_deps
            # 3. optional content fold-in.
            if title is not None:
                target.title = title.strip()[:512]
            if description is not None:
                target.description = description
            if acceptance is not None:
                target.acceptance = acceptance
            # 4. delete sources + renumber.
            for x in sources:
                s.delete(x)
            s.flush()
            self._renumber(s, pid)
