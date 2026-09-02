"""The task a run is actually given, built ONCE (ADR-0079 Wave 1, ADR-0082).

Extracted from the launch path so it has exactly one definition. The benchmark harness and any
future instrument must build the task the same way production does, or they grade a contract
production never sends — which is not a hypothetical: the clause tier's first measured A/B came
back null because the number was delivered through a channel the task string never touched.

Two invariants live here, and both are easy to break by re-deriving this by hand elsewhere:

* **Ratified standing decisions join the ACCEPTANCE CRITERIA**, not a separate section. The
  Proctor's authoring ask, the coder's implement instruction and the structural gate all read
  ``state["task"]``; a decision rendered anywhere else reaches none of them (measured 2026-08-05:
  0/12 control vs 0/4 treatment when it rode the planning overview instead).
* **Claims are minted from the WOVEN criteria**, never from the stored acceptance. Mint them from
  the stored text and the gate judges a different contract from the one the coder was handed.

The item is never mutated: the weave is per RUN, so retiring a clause takes effect on the next run
and can never rewrite work already delivered.

``acceptance_text`` is the WRITE-side counterpart to ``build_run_task``'s read: every path that
stores a model-authored acceptance normalises through it, so the newline-per-criterion shape the
readers all assume is established once, at the boundary, instead of being re-derived per call site.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.claims import claims_as_dicts, claims_from_acceptance
from mosaera_core.clauses import Clause, weave_criteria


def acceptance_text(value: Any) -> str:
    """A model-authored acceptance as the rest of the system reads it: one criterion per line.

    Models return an acceptance as a list of bullets often enough that ``str()`` would store a
    Python repr — ``['crit 1', 'crit 2']``, brackets and quotes included — as a single
    newline-free blob. Every reader splits on newlines, so the whole chain then sees exactly ONE
    criterion: the UI count, the claims minted for the gate, the task string handed to the coder
    and the Proctor, the checkability verdict, and the count fed back to Quincy (which is why the
    model cannot correct it when asked — it is told it already emitted one criterion).

    Joined, not rejected: the content is right and only the shape is off, so refusing it would
    lose a good proposal. Non-list values keep their existing ``str().strip()`` behaviour, so this
    is a no-op for every payload that was already correct.
    """
    if isinstance(value, list):
        return "\n".join(str(v).strip() for v in value if str(v).strip()).strip()
    return str(value or "").strip()


def build_run_task(
    item: dict[str, Any], clauses: tuple[Clause, ...] = ()
) -> tuple[str, list[dict[str, Any]]]:
    """``(task, claims)`` for one backlog item under the given standing decisions.

    The flattening order — title, description, then criteria — is the contract every prompt
    downstream was written against; it is preserved byte-for-byte.
    """
    task = str(item.get("title") or "")
    description = str(item.get("description") or "")
    if description:
        task += f"\n\n{description}"
    acceptance = str(item.get("acceptance") or "")
    # Relevance is judged on the WHOLE item, not the acceptance field alone: "refactor the checkout
    # function into a short orchestrator" is routinely the title or the description, and a clause
    # the item genuinely left open must not be dropped because of where the operator typed it.
    criteria = weave_criteria(acceptance, clauses, item_text=f"{task}\n\n{acceptance}")
    if criteria:
        task += f"\n\nAcceptance criteria:\n{criteria}"
    claims = claims_as_dicts(claims_from_acceptance(item.get("id"), criteria))
    return task, claims
