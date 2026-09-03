"""A pre-existing file emptied by the producer is an undeclared removal (ADR-0095 Am. 2).

MEASURED LIVE 2026-08-10, LedgerCLI item 88, guided run 20260810-170506-842612. The coder had no
delete tool and no git tool, and emptied four tracked build artefacts to simulate deleting them:

    src/budget_tracker.egg-info/PKG-INFO       +1 -4
    src/budget_tracker.egg-info/SOURCES.txt    +0 -11
    src/budget_tracker.egg-info/top_level.txt  +1 -1

No control examined it — not the reviewer, not an oracle, not the gate. F43's third recurrence, and
all three were caught by a human reading the diff.

The boundary tests below matter as much as the positive one: this check is admissible under
ADR-0085 §1 only because it is STRUCTURAL and ONE-SIDED, and each test pins one edge of that.
"""

from __future__ import annotations

from pathlib import Path

from mosaera_core.destruction import destroyed_paths, destruction_evidence


class _WS:
    """A workspace whose HEAD content is scripted."""

    def __init__(self, root: Path, head: dict[str, str]) -> None:
        self.root = root
        outer = self

        class _Git:
            @staticmethod
            def show(ref: str) -> str:
                rel = ref.split(":", 1)[1]
                if rel not in outer._head:
                    raise RuntimeError("absent at HEAD")
                return outer._head[rel]

        class _Repo:
            git = _Git()

        self._head = head
        self.repo = _Repo()


def _tree(tmp: Path, **files: str) -> Path:
    for name, body in files.items():
        p = tmp / name.replace("__", "/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp


def _diff(*paths: str) -> str:
    return "\n".join(f"--- a/{p}\n+++ b/{p}" for p in paths)


# --- the defect, reproduced -------------------------------------------------------------------


def test_a_pre_existing_file_emptied_is_flagged(tmp_path: Path) -> None:
    """THE REGRESSION — item 88's actual shape."""
    root = _tree(tmp_path, **{"pkg__PKG-INFO": ""})
    ws = _WS(root, {"pkg/PKG-INFO": "Metadata-Version: 2.4\nName: budget_tracker\n"})
    assert destroyed_paths(ws, _diff("pkg/PKG-INFO")) == ["pkg/PKG-INFO"]


def test_whitespace_only_counts_as_emptied(tmp_path: Path) -> None:
    """`+1 -4` left a single blank line — the live diff's exact shape."""
    root = _tree(tmp_path, **{"pkg__top_level.txt": "\n  \n"})
    ws = _WS(root, {"pkg/top_level.txt": "budget_tracker\n"})
    assert destroyed_paths(ws, _diff("pkg/top_level.txt")) == ["pkg/top_level.txt"]


def test_several_destroyed_files_are_all_named(tmp_path: Path) -> None:
    root = _tree(tmp_path, **{"a__x.txt": "", "a__y.txt": "", "a__keep.txt": "still here"})
    ws = _WS(root, {"a/x.txt": "one", "a/y.txt": "two", "a/keep.txt": "still here"})
    assert destroyed_paths(ws, _diff("a/x.txt", "a/y.txt", "a/keep.txt")) == ["a/x.txt", "a/y.txt"]


# --- the boundaries that keep it structural and one-sided -------------------------------------


def test_a_NEW_empty_file_is_ordinary_work(tmp_path: Path) -> None:
    """Absent at HEAD ⇒ no baseline ⇒ inert. Deny-by-default in the safe direction."""
    root = _tree(tmp_path, **{"pkg____init__.py": ""})
    assert destroyed_paths(_WS(root, {}), _diff("pkg/__init__.py")) == []


def test_a_file_already_empty_at_head_is_not_destroyed(tmp_path: Path) -> None:
    root = _tree(tmp_path, **{"pkg__marker.txt": ""})
    assert destroyed_paths(_WS(root, {"pkg/marker.txt": "\n"}), _diff("pkg/marker.txt")) == []


def test_a_merely_SHORTENED_file_is_silent(tmp_path: Path) -> None:
    """THE NARROW BOUNDARY. 'Shrank by N%' is a semantic judgment in a structural costume —
    there is no shape-derivable answer to how much loss is too much — and picking a threshold
    would start the accretion ADR-0085 §1 exists to stop."""
    root = _tree(tmp_path, **{"pkg__mod.py": "def keep():\n    return 1\n"})
    ws = _WS(root, {"pkg/mod.py": "def keep():\n    return 1\n" + "def gone():\n    pass\n" * 40})
    assert destroyed_paths(ws, _diff("pkg/mod.py")) == []


def test_an_HONEST_delete_is_not_this_defect(tmp_path: Path) -> None:
    """A file gone from the tree is a real delete — only the admin-gated `delete_file` can do it
    and the diff records it honestly. What this closes is the removal that HIDES."""
    root = _tree(tmp_path, **{"pkg__keep.py": "x = 1\n"})
    assert destroyed_paths(_WS(root, {"pkg/gone.py": "x = 1\n"}), _diff("pkg/gone.py")) == []


def test_test_files_are_left_to_the_tamper_guard(tmp_path: Path) -> None:
    """Two controls judging one tree is how they come to disagree about it."""
    root = _tree(tmp_path, **{"tests__test_a.py": ""})
    ws = _WS(root, {"tests/test_a.py": "def test_x() -> None:\n    assert 1\n"})
    assert destroyed_paths(ws, _diff("tests/test_a.py")) == []


def test_an_unchanged_file_is_never_examined(tmp_path: Path) -> None:
    root = _tree(tmp_path, **{"pkg__untouched.txt": ""})
    assert destroyed_paths(_WS(root, {"pkg/untouched.txt": "content"}), _diff("other.py")) == []


# --- the record, and the gate ------------------------------------------------------------------


def test_the_evidence_NAMES_what_was_destroyed() -> None:
    """A gate reason with no named path is the invisible-control defect this repo has measured
    four times: the operator is told a removal is unproven and left to re-derive which one."""
    text = destruction_evidence(["a/x.txt", "a/y.txt"])
    assert "a/x.txt" in text and "a/y.txt" in text
    assert "neither claimed nor proven" in text
    assert destruction_evidence([]) == ""


def test_a_destroyed_file_makes_the_gate_REFUSE() -> None:
    """THE WIRING. A prohibition, not a criterion: no claim, no id — a flag, like tamper."""
    from mosaera_policies.gate import evaluate_gate

    def decide(destroyed: bool) -> tuple[list[str], str]:
        d = evaluate_gate(
            tests_passed=True,
            reviewer_verdict="APPROVE",
            findings_count=0,
            iteration=1,
            max_iterations=6,
            oracle_verified=True,
            validation_strength="strong",
            content_destroyed=destroyed,
        )
        return list(d.reasons), d.action

    assert decide(False) == ([], "deliver"), "inert when nothing was destroyed"
    reasons, action = decide(True)
    assert reasons == ["content_destroyed"]
    assert action != "deliver", "an otherwise-perfect run must NOT ship after gutting a file"


def test_the_prohibition_cannot_be_waived_by_a_clause() -> None:
    """It fires precisely BECAUSE no proof was offered, so a waiver would erase the only record
    that content was destroyed at all."""
    from mosaera_policies.standards import PROOF_BEARING

    assert "content_destroyed" in PROOF_BEARING


def test_it_is_in_the_tamper_family() -> None:
    """Same class as `tests_tampered`: nothing for the coder to 'finish', admissible-set nil."""
    from mosaera_policies.gate import REASON_CLASS

    assert REASON_CLASS["content_destroyed"] == REASON_CLASS["tests_tampered"] == "tamper"
