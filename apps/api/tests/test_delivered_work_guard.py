"""A changeset may not delete the record of delivered work.

Measured 2026-08-19. Asked to tidy a live backlog, the PM proposed deleting twelve items — five of
them `done` or `in_review`, with runs and branches behind them. Asked in the SAME conversation
whether that was safe, it answered no and explained exactly what would be lost ("would erase the
record", "discard the pending work and its MR"). The knowledge was there; the path that produced
the ops did not use it.

So this is a deterministic guard rather than a prompt fix. A control that depends on which code
path the model happened to take is not a control, and the operator most likely to click Apply is
the one least able to audit what it does.

The store's `_refuse_if_mr_live` already covers a row whose merge request is OPEN. It does not
cover the state these tests are about: work delivered with NO merge request, which is what the
`delivered_no_mr` decision reports and the majority state on an autonomously-run project.
"""

from __future__ import annotations

from typing import Any

import pytest
from mosaera_api.projects import apply_backlog_changeset


class _Mem:
    """Just the reads the validator makes, plus a record of what got destroyed."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self.deleted: list[int] = []
        self.split: list[int] = []
        self.merged: list[list[int]] = []

    def list_backlog_items(self, project_id: str) -> list[dict[str, Any]]:
        return list(self._items)

    def delete_backlog_item(self, item_id: int) -> None:
        self.deleted.append(item_id)
        self._items = [i for i in self._items if int(i["id"]) != item_id]

    def split_backlog_item(self, item_id: int, parts: list[dict[str, str]]) -> list[int]:
        self.split.append(item_id)
        return []

    def merge_backlog_items(self, target: int, sources: list[int], **kw: Any) -> None:
        self.merged.append(sorted(sources))


def _item(item_id: int, status: str, **over: Any) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": f"item {item_id}",
        "description": "",
        "acceptance": "",
        "status": status,
        "mr_url": "",
        "branch": "",
        "position": item_id,
        **over,
    }


#: The five destructive ops from the real proposal, verbatim in shape.
_QUINCYS_PROPOSAL = [
    {"op": "delete", "id": 84, "why": "Slice 2 already completed and present in repository"},
    {"op": "delete", "id": 85, "why": "Slice 3 already completed and present in repository"},
    {"op": "delete", "id": 86, "why": "Slice 4 already completed and present in repository"},
    {"op": "delete", "id": 87, "why": "Slice 5 already completed and present in repository"},
    {"op": "delete", "id": 104, "why": "not required by project brief"},
]

_LIVE_BACKLOG = [
    _item(84, "done"),
    _item(85, "done"),
    _item(86, "done"),
    _item(87, "done"),
    _item(104, "in_review"),
    _item(91, "deferred"),
    _item(96, "deferred"),
]


def test_the_real_proposal_is_refused_whole() -> None:
    """The changeset that prompted this guard, applied against the backlog it was written for."""
    mem = _Mem(list(_LIVE_BACKLOG))
    with pytest.raises(ValueError) as exc:
        apply_backlog_changeset(mem, "p1", _QUINCYS_PROPOSAL)  # type: ignore[arg-type]

    message = str(exc.value)
    assert "delivered work" in message
    for named in ("#84", "#85", "#86", "#87", "#104"):
        assert named in message, f"{named} was not named in the refusal"
    assert mem.deleted == [], "a row was destroyed despite the refusal"


def test_a_safe_op_in_the_same_set_is_refused_too() -> None:
    """Whole-set rejection, not per-op skipping. Each op is its own transaction, so applying the
    safe half of a rejected changeset would leave the backlog in a state nobody proposed — the
    reason the surrounding validator rejects the whole set before anything is written."""
    mem = _Mem(list(_LIVE_BACKLOG))
    mixed = [{"op": "delete", "id": 91}, {"op": "delete", "id": 84}]

    with pytest.raises(ValueError):
        apply_backlog_changeset(mem, "p1", mixed)  # type: ignore[arg-type]

    assert mem.deleted == [], "the safe op was applied out of a rejected set"


def test_deleting_undelivered_duplicates_still_works() -> None:
    """The guard must not block the cleanup it was written alongside. #91 and #96 are the
    duplicates the same conversation correctly identified, and neither is delivered."""
    mem = _Mem(list(_LIVE_BACKLOG))

    ops = [{"op": "delete", "id": 91}, {"op": "delete", "id": 96}]
    apply_backlog_changeset(mem, "p1", ops)  # type: ignore[arg-type]

    assert sorted(mem.deleted) == [91, 96]


def test_split_and_merge_destroy_rows_too() -> None:
    """`split` deletes the parent it replaces and `merge` deletes every source it folds in. The
    store's MR guard had to cover all three doors; so does this one."""
    for changeset, verb in (
        ([{"op": "split", "id": 84, "parts": [{"title": "a"}, {"title": "b"}]}], "split"),
        ([{"op": "merge", "target": 91, "sources": [84]}], "merge"),
    ):
        mem = _Mem(list(_LIVE_BACKLOG))
        with pytest.raises(ValueError) as exc:
            apply_backlog_changeset(mem, "p1", changeset)  # type: ignore[arg-type]
        assert "#84" in str(exc.value), verb
        assert mem.split == [] and mem.merged == [], verb


def test_an_item_carrying_a_branch_or_mr_is_protected_whatever_its_status() -> None:
    """Status is not the only evidence of delivery. A row carrying a branch or an MR url is what
    branch protection reads, so destroying it unprotects a branch regardless of the status text."""
    for over in ({"branch": "mosaera/item-70"}, {"mr_url": "https://gl/x/-/merge_requests/4"}):
        mem = _Mem([_item(70, "todo", **over)])
        with pytest.raises(ValueError):
            apply_backlog_changeset(mem, "p1", [{"op": "delete", "id": 70}])  # type: ignore[arg-type]
        assert mem.deleted == []


def test_the_operator_can_still_override_but_the_changeset_cannot() -> None:
    """The override is a parameter of the human's call, never a field on an op.

    The threat is a model-authored changeset an operator accepts. A permission flag living INSIDE
    the changeset would be granted by the same text it guards, so an op that asks for it must have
    no effect (ADR-0105: authority flows from the authenticated request, never from model output).
    """
    mem = _Mem(list(_LIVE_BACKLOG))
    self_permitting = [
        {"op": "delete", "id": 84, "allow_delivered": True, "confirmed": True, "force": True}
    ]
    with pytest.raises(ValueError):
        apply_backlog_changeset(mem, "p1", self_permitting)  # type: ignore[arg-type]
    assert mem.deleted == []

    # The operator's own call may do it deliberately.
    ok = [{"op": "delete", "id": 84}]
    apply_backlog_changeset(mem, "p1", ok, allow_delivered=True)  # type: ignore[arg-type]
    assert mem.deleted == [84]
