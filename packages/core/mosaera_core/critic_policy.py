"""Deterministic disposal of the critic's per-claim proposals (#61, ADR-0065 amendment).

The measured defect: the held-out critic vetoed grader-passing work 12x vs 5 true catches
(~29% precision; engineering-history/claims-gate-ab-2026-08-03.md) — the 20b judge does not
reliably obey its own "when unsure, SHIP" persona (a risk ADR-0065 pre-registered). The fix is
structural, not a better prompt: **the critic proposes, this module disposes.** A REFUTED
proposal counts only when BOTH of its verbatim quotes verify deterministically:

- the REQUIREMENT quote occurs (normalized substring) in the task/claims text — a critic that
  invents or paraphrases a requirement convicts nobody;
- the EVIDENCE quote occurs in the diff or test output — invented evidence convicts nobody.

SUPPORTED and INSUFFICIENT_EVIDENCE never veto (abstention is not a park — the owner's
standing ruling). The gate seam is unchanged: `outcome_verdict["vetoed"]` stays the only bit
`evaluate_gate` ever sees, still veto-only, still downgrade-only.

Adversarial note (in lieu of a policies red-team — this module is core, the trust boundary is
untouched): the quotes are matched against the REQUIREMENTS side and the DELIVERED side
separately. A requirement smuggled into delivered code (a comment that says "prints its new
id") does not make that text a requirement — the requirement corpus is task+claims only,
which are launch-minted from operator-approved text, never workspace content.
"""

from __future__ import annotations

import re
from typing import Any

_WS = re.compile(r"\s+")
_MIN_QUOTE_CHARS = 12  # a quote too short to identify anything can't convict either


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip().casefold()


def _occurs(quote: str, corpus: str) -> bool:
    q = _norm(quote)
    return len(q) >= _MIN_QUOTE_CHARS and q in corpus


def verify_rows(
    rows: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    task: str,
    diff: str,
    test_output: str,
) -> list[dict[str, Any]]:
    """Return the rows with a deterministic ``verified`` flag on each REFUTED proposal.

    Pure; same inputs → same output. Non-REFUTED rows pass through with ``verified: True``
    (they carry no authority, so there is nothing to verify — recording them is the point).
    """
    requirement_corpus = _norm(
        task + " " + " ".join(str(c.get("text", "")) for c in claims if isinstance(c, dict))
    )
    delivered_corpus = _norm(diff + " " + test_output)
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        if str(row.get("verdict", "")).upper() == "REFUTED":
            row["verified"] = _occurs(
                str(row.get("requirement_quote", "")), requirement_corpus
            ) and _occurs(str(row.get("evidence_quote", "")), delivered_corpus)
        else:
            row["verified"] = True
        out.append(row)
    return out


def dispose(
    judged: dict[str, Any] | None,
    claims: list[dict[str, Any]],
    task: str,
    diff: str,
    test_output: str,
    dispositions: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """The outer policy: rows → the gate-facing ``outcome_verdict`` shape.

    ``vetoed`` is True iff a VERIFIED REFUTED row lands on a MATERIAL claim INSIDE the
    critic's jurisdiction. Three tightenings from the aborted 2026-08-03 A/B (20 runs, every
    over-veto diagnosed from the persisted rows):

    - **Residual jurisdiction**: when per-claim deterministic dispositions are supplied, the
      critic may veto ONLY claims determinism could not cover (``unevaluable``/absent). A
      deterministic ``satisfied`` outranks a model REFUTED (Deterministic Final Authority); a
      deterministic ``failed`` already parks via ``unsatisfied_claim``.

      **NARROWED 2026-08-11 — ``unbound`` removed**, see the `residual` assignment below for the
      measurement. Two records disagree and both are stated rather than one silently overwriting
      the other: this docstring previously asserted the residual record "is 5-for-5", a figure
      with **no source anywhere in `docs/`** (only this comment). The 260-run corpus measured
      2026-08-11 reads **0-for-9**. If those 5 were ``unevaluable`` claims, this narrowing
      preserves exactly that authority and the two records are compatible.
    - **Unknown claim ids are NOT material** (was ``.get(id, True)`` — deny-by-default
      pointing the wrong way; an invented id could veto).
    - **Format-noncompliance is abstention, not the legacy verdict**: the aborted A/B showed
      the fallback leaking the OLD over-veto failure (3 of 5). No structured rows → no veto;
      the legacy reason is recorded advisory-only.

    Discarded refutations and abstentions are recorded in ``rows`` — everything is auditable,
    the gate sees one honest bit.
    """
    if judged is None:
        return None
    rows = judged.get("rows") or []
    if not rows:
        fb = judged.get("fallback")
        if isinstance(fb, dict):
            return {
                "vetoed": False,  # no structured evidence → no authority (measured leak)
                "reason": "advisory (format-noncompliant, no veto authority): "
                + str(fb.get("reason", ""))[:400],
                "rows": [],
            }
        return None
    material = {
        str(c.get("id")): bool(c.get("material", True)) for c in claims if isinstance(c, dict)
    }
    covered = {
        str(d.get("claim_id")): str(d.get("verdict", ""))
        for d in (dispositions or [])
        if isinstance(d, dict)
    }
    # `unbound` is DELIBERATELY absent (2026-08-11). A claim the deterministic layer scored
    # `unbound` is one with no oracle at all, and the gate DISCARDS those by owner decision
    # (2026-08-03, "unbound claims are intake's job, never the gate's"). Leaving it in the
    # residual let a MODEL park a run on evidence the deterministic layer had explicitly refused
    # to gate on — the inverse of Deterministic Final Authority.
    #
    # Measured: 9 vetoes across 260 runs, ALL NINE refusing work the hidden grader confirms was
    # correct; 8 of them quoting a PREMISE sentence ("crashes on the first malformed op", "the
    # existing test asserts the OLD unrounded result"). A premise describes the state the item
    # exists to CHANGE, so a correct fix necessarily falsifies it and the run is refused for
    # succeeding. Premise sentences classify as `oracle_kind: none` -> `unbound`, so removing
    # `unbound` closes the whole class BY CONSTRUCTION rather than by pattern — the third attempt
    # at this class, after `_PREMISE` regex extensions in MCB-03 and MCB-13.
    residual = {"unevaluable", ""}
    verified = verify_rows(rows, claims, task, diff, test_output)
    vetoing = [
        r
        for r in verified
        if r["verdict"] == "REFUTED"
        and r["verified"]
        and material.get(r["claim_id"], False)  # unknown id: never material
        and covered.get(r["claim_id"], "") in residual  # jurisdiction: the residual only
    ]
    reason = (
        "; ".join(
            f"claim {r['claim_id']}: {r['requirement_quote']!r} unmet — {r['evidence_quote']!r}"
            for r in vetoing[:3]
        )[:500]
        or "no verified refutation"
    )
    return {"vetoed": bool(vetoing), "reason": reason, "rows": verified}
