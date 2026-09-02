"""Stage 1 of the Layer-2 revival: the disposition's authored test gets the #62 mined inputs.

The 2026-08-09 deferral measured 0 conversions in 13 eligible parks; #62 measured that mined
boundary triples fix exactly that wall (0/20 -> 20/20 mutation_caught). This pins the handoff:
the mined values reach the INSTRUCTION (the model still authors, the deterministic checks still
decide), and an empty mine leaves the instruction byte-identical.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.disposition import _author_instruction, _mined_inputs_block
from mosaera_core.input_mining import mined_boundaries


def test_the_miner_produces_offbyone_triples_around_source_literals() -> None:
    src = "def check(age):\n    if not (0 <= age <= 150):\n        raise ValueError(age)\n"
    mined = mined_boundaries(src)
    # 149/150/151 are the MCB-14 killers the generic set could never reach.
    assert {149, 150, 151} <= set(mined)


class _WS:
    """Minimal workspace: one changed non-test module carrying a threshold literal."""

    def __init__(self, tmp: Any) -> None:
        self.root = tmp
        (tmp / "mod.py").write_text(
            "def check(age):\n    if not (0 <= age <= 150):\n        raise ValueError(age)\n"
        )

    def diff_all(self) -> str:
        return "--- a/mod.py\n+++ b/mod.py\n@@ -1 +1 @@\n+def check(age): ...\n"


def test_mined_values_reach_the_authoring_instruction(tmp_path: Any) -> None:
    block = _mined_inputs_block(_WS(tmp_path))  # type: ignore[arg-type]
    assert "151" in block and "149" in block, "the off-by-one triple must be handed to the model"
    assert "wrong-typed" in block
    inst = _author_instruction("acc", "task", block)
    assert "151" in inst


def test_an_empty_mine_leaves_the_instruction_byte_identical(tmp_path: Any) -> None:
    """The positive control for scope: no mined values -> no new text, so every existing
    behaviour (and its measurements) is untouched on modules with no integer literals."""

    class _Empty(_WS):
        def __init__(self, tmp: Any) -> None:
            self.root = tmp
            (tmp / "mod.py").write_text("def go(x):\n    return x\n")

    assert _mined_inputs_block(_Empty(tmp_path)) == ""  # type: ignore[arg-type]
    assert _author_instruction("a", "t", "") == _author_instruction("a", "t")


def test_a_faulting_workspace_yields_the_empty_block_never_a_crash(tmp_path: Any) -> None:
    class _Broken:
        root = tmp_path

        def diff_all(self) -> str:
            raise OSError("gone")

    assert _mined_inputs_block(_Broken()) == ""  # type: ignore[arg-type]
