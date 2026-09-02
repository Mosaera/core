"""MODIFY: a behaviour change must know who it breaks (verb-arc slice 4).

When an item deliberately changes behaviour, the test asserting the OLD behaviour fails. The gate
sees `validation_failed` — **indistinguishable from "the code is wrong"**. So the run grinds to the
cap against a test it may not touch, or the coder edits that test and the change ships with its own
contract rewritten. Nothing records that the failure was the point.

Measured before building (25 briefs, 372 claims): `Change \\`load_config\\` to return …` mints
`acceptance_test` today, whose oracle is `state["tests_passed"]` VERBATIM. So MODIFY did not mint
*nothing* — it minted a claim that cannot tell *"the test failed"* from *"the test was supposed
to fail"*. They are the same boolean.

**The oracle is the discriminator, not the pattern.** A MODIFY verb is how ordinary work is
described, so the filter is a fact no regex can see: did the symbol exist at HEAD? That inverts
slice 1, where `_REMOVAL` had to be narrow because `non_use_proven` could not make the distinction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mosaera_core.claim_oracles import evaluate_claims, failed_claim_classes
from mosaera_core.claims import CLAIM_EVIDENCE_CLASS, ORACLE_KINDS, classify_sentence
from mosaera_core.nonuse import consumers_of


class _Repo:
    """A stand-in for `workspace.repo.git`, holding the HEAD content of each path."""

    def __init__(self, head: dict[str, str]) -> None:
        self.git = self
        self._head = head

    def show(self, spec: str) -> str:
        rel = spec.split(":", 1)[1]
        if rel not in self._head:
            raise RuntimeError(f"fatal: path '{rel}' does not exist in 'HEAD'")
        return self._head[rel]


class _WS:
    def __init__(self, root: Path, head: dict[str, str] | None = None) -> None:
        self.root = root
        self.repo = _Repo(head or {})

    def diff_all(self) -> str:
        return ""


def _tree(tmp: Path, **files: str) -> Path:
    for name, body in files.items():
        p = tmp / name.replace("__", "/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp


def _claim(text: str) -> list[dict[str, Any]]:
    return [{"id": "c1", "oracle_kind": "consumer_impact", "text": text, "material": True}]


_SAY = "Change `apply_discount` to round to two decimals."
_DEF = "def apply_discount(t, p):\n    return t * p\n"


# --- the claim -----------------------------------------------------------------------------


def test_a_modify_sentence_binds_the_impact_oracle() -> None:
    for s in (
        "Change `apply_discount` to round to two decimals.",
        "- Update `render_row` so the width defaults to 20.",
        "The `legacy_flag` should be renamed to `compat_flag`.",
    ):
        assert classify_sentence(s)[0] == "consumer_impact", s


def test_it_loses_to_removal_and_beats_behavioural() -> None:
    """Ordering. A removal is a modification in the loosest sense and its oracle is stronger; a
    behavioural claim would swallow this and restate `tests_passed`, losing the whole point."""
    assert classify_sentence("Remove the deprecated `legacy_export` function.")[0] == "non_use"
    assert classify_sentence("Change `f` to return None.")[0] == "consumer_impact"
    assert classify_sentence("Do not delete or modify the existing tests.")[0] == "tests_unmodified"


def test_the_pattern_mints_nothing_spurious_on_real_briefs() -> None:
    """MEASURED, and it reversed a planning assumption. Of 14 sentences across the 25 shipped
    briefs containing a modify verb, ZERO are behaviour-change items — they are "persist the
    change" (a noun), "after your change:" (a discourse marker), "Do not change any observable
    behaviour" (a refactor's PRESERVATION clause, the opposite claim) and `update_user` (an API
    name). Widening the pattern to catch those would mint on all of them.

    MCB-28 is the only case that should mint, and it exists because the corpus had no MODIFY item —
    exactly as it had no SUBTRACT item before MCB-27.
    """
    from mosaera_core.claims import claims_from_acceptance

    cases = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "cases"
    minting = set()
    for brief in sorted(cases.glob("*/brief.md")):
        for c in claims_from_acceptance(None, brief.read_text(encoding="utf-8")):
            if c.oracle_kind == "consumer_impact":
                minting.add(brief.parent.name)
    assert minting == {"MCB-28"}, f"unexpected minting: {minting}"


def test_the_evidence_class_is_its_own() -> None:
    """Not `structural`, for slice 1's reason: Layer 2 verifies by authoring a BEHAVIOURAL test and
    mutating it — the very evidence a behaviour CHANGE invalidates."""
    assert "consumer_impact" in ORACLE_KINDS
    assert CLAIM_EVIDENCE_CLASS["consumer_impact"] == "impact"
    covered = set(CLAIM_EVIDENCE_CLASS) | {"none"}
    assert covered == set(ORACLE_KINDS)


# --- consumer enumeration ---------------------------------------------------------------------


def test_the_definer_is_not_its_own_consumer(tmp_path: Path) -> None:
    """Counting the defining file would make "someone depends on this" true for every symbol that
    exists, and the witness test trivially passable."""
    root = _tree(tmp_path, **{"m.py": _DEF, "user.py": "from m import apply_discount\n"})
    refs, defs = consumers_of(root, "apply_discount") or ([], [])
    assert defs == ["m.py"]
    assert refs == ["user.py"]


def test_scratch_is_not_a_consumer(tmp_path: Path) -> None:
    root = _tree(tmp_path, **{"m.py": _DEF, ".mosaera__s.py": "apply_discount(1, 2)\n"})
    refs, _ = consumers_of(root, "apply_discount") or ([], [])
    assert refs == []


# --- THE FILTER: the oracle, not the regex, decides ---------------------------------------------


def test_a_new_symbol_is_not_a_modification(tmp_path: Path) -> None:
    """THE design. The sentence matched, but the symbol did not exist at HEAD — so nothing could
    have depended on a previous behaviour. This is what makes minting broadly safe."""
    ws = _WS(_tree(tmp_path, **{"m.py": _DEF}), head={})  # absent at HEAD ⇒ new
    row = evaluate_claims(_claim(_SAY), ws, {})[0]
    assert row["verdict"] == "satisfied"
    assert "new in this change" in row["oracle_ref"]


def test_a_new_symbol_in_an_EXISTING_file_is_still_new(tmp_path: Path) -> None:
    """Symbol-level, not file-level — a defect in the first version of this. A brand-new function
    added to a pre-existing file is new code, and a file-level check would demand a witness for
    something nothing could have depended on."""
    ws = _WS(_tree(tmp_path, **{"m.py": _DEF}), head={"m.py": "def other():\n    return 1\n"})
    assert evaluate_claims(_claim(_SAY), ws, {})[0]["verdict"] == "satisfied"


def test_a_witnessed_change_is_satisfied_and_names_the_witness(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        **{
            "m.py": _DEF,
            "user.py": "from m import apply_discount\n",
            "tests__test_m.py": "from m import apply_discount\n",
        },
    )
    ws = _WS(root, head={"m.py": _DEF})
    row = evaluate_claims(_claim(_SAY), ws, {})[0]
    assert row["verdict"] == "satisfied"
    assert "tests/test_m.py" in row["oracle_ref"]


def test_an_unwitnessed_change_FAILS_and_names_who_is_affected(tmp_path: Path) -> None:
    """The Hyrum's-Law case: consumers exist, nothing asserts the new behaviour. A park must say
    WHO is affected, not merely that something is."""
    root = _tree(tmp_path, **{"m.py": _DEF, "user.py": "from m import apply_discount\n"})
    ws = _WS(root, head={"m.py": _DEF})
    row = evaluate_claims(_claim(_SAY), ws, {})[0]
    assert row["verdict"] == "failed"
    assert "user.py" in row["oracle_ref"]


def test_deny_by_default_when_unaskable(tmp_path: Path) -> None:
    ws = _WS(_tree(tmp_path, **{"m.py": _DEF}), head={"m.py": _DEF})
    assert evaluate_claims(_claim("Change the helper."), ws, {})[0]["verdict"] == "failed"
    assert evaluate_claims(_claim(_SAY), object(), {})[0]["verdict"] == "failed"


def test_an_unreadable_HEAD_assesses_rather_than_waves_through(tmp_path: Path) -> None:
    """Deny-by-default in the filter itself: if we cannot tell whether it pre-existed, ASSESS it.
    Guessing "new" would wave a real behaviour change through unexamined."""
    root = _tree(tmp_path, **{"m.py": _DEF, "user.py": "from m import apply_discount\n"})
    ws = _WS(root, head={"m.py": "def ((( broken\n"})
    assert evaluate_claims(_claim(_SAY), ws, {})[0]["verdict"] == "failed"


def test_a_failed_claim_reaches_the_gate_as_the_impact_class(tmp_path: Path) -> None:
    claims = _claim(_SAY)
    root = _tree(tmp_path, **{"m.py": _DEF, "user.py": "from m import apply_discount\n"})
    rows = evaluate_claims(claims, _WS(root, head={"m.py": _DEF}), {})
    assert failed_claim_classes(rows, claims) == ["impact"]


def test_a_MOVED_symbol_is_still_a_modification(tmp_path: Path) -> None:
    """RED TEAM R2, confirmed and fixed. Checking only the symbol's CURRENT defining files misses
    a symbol that MOVED: the new file is absent at HEAD, so a real modification read as "new code"
    and its consumers went unassessed — a false `satisfied`, the only unsafe direction here.

    The fix is not a patch but a better question. Hyrum's Law is about DEPENDANTS, so a
    pre-existing CONSUMER is itself proof the behaviour could already be depended on.
    """
    root = _tree(
        tmp_path, **{"new_home.py": _DEF, "user.py": "from new_home import apply_discount\n"}
    )
    ws = _WS(root, head={"old_home.py": _DEF, "user.py": "from old_home import apply_discount\n"})
    row = evaluate_claims(_claim(_SAY), ws, {})[0]
    assert row["verdict"] == "failed", "a moved symbol was waved through as new code"
    assert "user.py" in row["oracle_ref"]


def test_a_genuinely_new_symbol_with_new_consumers_stays_satisfied(tmp_path: Path) -> None:
    """The other side of R2's fix: it must not disable the filter. Nothing at HEAD ⇒ new code."""
    root = _tree(tmp_path, **{"m.py": _DEF, "user.py": "from m import apply_discount\n"})
    row = evaluate_claims(_claim(_SAY), _WS(root, head={}), {})[0]
    assert row["verdict"] == "satisfied"
    assert "new in this change" in row["oracle_ref"]
