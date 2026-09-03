"""Which acceptance criteria of an item actually have evidence? — the reconciliation.

The North Star names this as Quincy's defining question: he *"never trusts 'Done'. It asks does
every acceptance criterion now have evidence?, not did Forge finish?"* (`north-star.md:157`). The
claim ledger (ADR-0079) records "what was promised, what proved it, what happened" per run, and
until now it was queryable only BY RUN — so the question could be answered about one execution and
never about a piece of work.

Reconciling needs BOTH halves and neither alone is enough:

* the item's CURRENT acceptance text, from which claims are derived at every launch, and
* the ledger rows, which record what past runs actually evaluated.

The gap between them is the whole point. A criterion the operator added after the last run has no
row at all — and that is `UNMEASURED`, which is neither satisfied nor failed. Collapsing an absent
measurement into either would be exactly the false-green this project keeps finding, so absence is
a first-class verdict here rather than a missing key.

Pure: takes text plus rows, returns a reconciliation. No store, no model, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mosaera_core.claims import claims_from_acceptance

#: A criterion the ledger has never evaluated. NOT a failure — nobody has looked.
UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class CriterionEvidence:
    """One acceptance criterion and the last thing a run said about it."""

    claim_id: str
    text: str
    verdict: str  # a ledger verdict, or UNMEASURED
    material: bool = True
    oracle_ref: str = ""

    @property
    def has_evidence(self) -> bool:
        """Only a run that actually evaluated it counts. `unbound`/`unevaluable` are the ledger's
        own honest non-answers and must not read as evidence either."""
        return self.verdict in ("satisfied", "failed")


@dataclass(frozen=True)
class ItemEvidence:
    criteria: tuple[CriterionEvidence, ...]

    @property
    def measured(self) -> int:
        return sum(1 for c in self.criteria if c.has_evidence)

    @property
    def satisfied(self) -> int:
        return sum(1 for c in self.criteria if c.verdict == "satisfied")

    @property
    def unmeasured(self) -> tuple[CriterionEvidence, ...]:
        return tuple(c for c in self.criteria if not c.has_evidence)

    @property
    def fully_evidenced(self) -> bool:
        """Every MATERIAL criterion satisfied. Immaterial ones (quality-soft phrasing) inform
        review but never gate, so they cannot hold an item back here either."""
        material = [c for c in self.criteria if c.material]
        return bool(material) and all(c.verdict == "satisfied" for c in material)


def reconcile(acceptance: str, ledger_rows: list[dict[str, Any]], item_id: int) -> ItemEvidence:
    """The item's CURRENT criteria, each with the newest verdict the ledger holds for it.

    Driven by the acceptance text, not by the rows: a criterion that was deleted from the item still
    has ledger rows, and reporting it would describe a bar nobody is held to any more. The text is
    the promise; the ledger is only what happened to it.
    """
    by_claim = {str(r.get("claim_id")): r for r in ledger_rows}
    out: list[CriterionEvidence] = []
    for claim in claims_from_acceptance(item_id, acceptance):
        row = by_claim.get(claim.id)
        out.append(
            CriterionEvidence(
                claim_id=claim.id,
                text=claim.text,
                verdict=str(row.get("verdict")) if row else UNMEASURED,
                material=claim.material,
                oracle_ref=str(row.get("oracle_ref") or "") if row else "",
            )
        )
    return ItemEvidence(criteria=tuple(out))
