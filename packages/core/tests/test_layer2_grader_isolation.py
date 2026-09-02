"""The hidden answer key must never be inside the tree Layer 2 judges (F85).

FOUND 2026-08-09, mid-sweep, in a live workspace:

    bench-MCB-13-.../
      _mcb_grader/test_acceptance.py   <- the hidden acceptance suite
      tests/                            <- where Layer 2 authors its "independent" test

`grade()` copies the answer key into the workspace and never removes it, and grading runs BEFORE
the Layer-2 attempt. The green step runs `pytest` at the workspace root with only
`--ignore=.mosaera`, so it COLLECTED the answer key; and the tester authors with repo tools that
can READ the tree, so its "independent" test could be copied from the key beside it.

The data signature was unmistakable: **6 of 7 grader-WRONG deliveries failed the green step, and
0 of 6 grader-RIGHT ones did** — a perfect separation produced by an authored test the same cards
show is a rubber stamp 4 times in 7.

Why this one matters more than an ordinary bug: it makes the bench read **SAFER than production**.
Production Layer 2 has no answer key, so the benchmark was granting the mechanism an oracle the
real system will never have — while that benchmark was the evidence for switching it on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mosaera_core.bench.faithfulness import POISON_SENTINEL
from mosaera_core.bench.grade import GRADER_DIR
from mosaera_core.bench.layer2 import (
    _purge_grader,
    assert_judgeable,
    try_layer2_conversion,
)


class _WS:
    def __init__(self, root: Path) -> None:
        self.root = root


def test_the_grader_is_purged_from_the_judged_tree(tmp_path: Path) -> None:
    grader = tmp_path / GRADER_DIR
    grader.mkdir()
    (grader / "test_acceptance.py").write_text("def test_truth(): assert True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    assert _purge_grader(_WS(tmp_path)) is True
    assert not grader.exists(), "the answer key survived inside the tree Layer 2 judges"
    assert (tmp_path / "tests").exists(), "the purge must not touch the delivered tests"


def test_purge_is_a_no_op_when_there_is_no_grader(tmp_path: Path) -> None:
    """Production has no answer key — the purge must be silent there, not an error path."""
    assert _purge_grader(_WS(tmp_path)) is True


def test_a_failed_purge_declines_instead_of_measuring(monkeypatch: Any, tmp_path: Path) -> None:
    """FAIL CLOSED. A measurement taken with the answer key still present would read as a SAFE
    result, and a safe-looking result is what gets a bad mechanism switched on. Refusing to
    measure is the only honest option, so the attempt declines with the reason recorded.
    """
    import mosaera_core.bench.layer2 as mod

    (tmp_path / GRADER_DIR).mkdir()
    monkeypatch.setattr(mod, "_purge_grader", lambda ws: False)

    run = type("R", (), {"workspace": _WS(tmp_path), "final": {}})()
    out = try_layer2_conversion(run, object(), object(), "subprocess", "oracle_unverified")  # type: ignore[arg-type]
    assert out.verdict is None
    assert "purge" in out.reason


def test_the_grader_dir_name_has_one_origin() -> None:
    """`layer2.py` imports the constant rather than repeating the string. A second copy is how
    the purge and the injection would silently stop referring to the same directory."""
    src = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "layer2.py"
    text = src.read_text(encoding="utf-8")
    assert "GRADER_DIR" in text
    assert '"_mcb_grader"' not in text, "layer2.py hard-codes the grader dir — import it instead"


# --- the SECOND contaminant: the reference solution overlaid on the delivered tree --------------


def test_a_reference_overlaid_tree_is_refused(tmp_path: Path) -> None:
    """THE near-miss, made impossible.

    `overstrict_vs_reference` overwrites the delivered code with the case's correct solution and
    leaves it there. Layer 2 avoided judging that tree only because it happens to run at line 150
    of a dict literal while the overlay runs at line 178 — safety by evaluation order. Anything
    added after that point would have judged a tree where the agent appears to have written a
    flawless solution, and converted it.

    Unlike the answer key, this cannot be cleaned up: the delivered work is *gone*, overwritten.
    Refusing is the only honest response.
    """
    (tmp_path / POISON_SENTINEL).write_text("reference overlaid", encoding="utf-8")
    why = assert_judgeable(_WS(tmp_path))
    assert why, "a tree carrying the reference solution was accepted as the agent's work"
    assert "reference" in why


def test_the_overlay_marks_the_tree_before_it_runs_anything(tmp_path: Path) -> None:
    """The marker must be written BEFORE the overlay's own sandbox work, so a crash mid-measurement
    still leaves a poisoned tree labelled — the unlabelled window is zero, not merely short."""
    import inspect

    from mosaera_core.bench import faithfulness

    src = inspect.getsource(faithfulness.overstrict_vs_reference)
    assert src.index("POISON_SENTINEL") < src.index("create_sandbox"), (
        "the poison marker is written after the overlay runs — a crash in between leaves the "
        "reference solution in place with nothing saying so"
    )


def test_ordering_independence_is_a_mechanism_not_a_comment(tmp_path: Path) -> None:
    """Run the overlay's effect FIRST, then attempt a conversion: it must decline.

    This is the exact sequence that was safe only by luck. If this test fails, the bench can once
    again judge the reference solution as if it were the agent's work.
    """
    (tmp_path / POISON_SENTINEL).write_text("reference overlaid", encoding="utf-8")
    run = type("R", (), {"workspace": _WS(tmp_path), "final": {}})()
    out = try_layer2_conversion(run, object(), object(), "subprocess", "oracle_unverified")  # type: ignore[arg-type]
    assert out.verdict is None, "a poisoned tree produced a Layer-2 verdict"
    assert "reference" in out.reason


def test_the_sentinel_name_has_one_origin() -> None:
    """The writer defines it; the checker imports it. Two copies is how a marker and its check
    silently stop referring to the same file."""
    root = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench"
    assert '"_MCB_POISONED"' not in (root / "layer2.py").read_text(encoding="utf-8")


# --- the diagnostic must never become a gate ---------------------------------------------------


def test_the_grader_probe_cannot_reach_the_verdict() -> None:
    """The probe uses the ANSWER KEY. If it could influence `l2`, the benchmark's independent judge
    would also be the deciding mechanism, and the false-ship rate would be unmeasurable by
    construction — the exact contamination F85 was.

    Pinned structurally: the probe runs strictly after the verdict is computed, and never assigns
    to it.
    """
    import inspect

    from mosaera_core.bench import cli

    src = inspect.getsource(cli._run_once)
    verdict_at = src.index("l2 = try_layer2_conversion")
    probe_at = src.index("grader_catches_a_mutation")
    assert verdict_at < probe_at, "the grader probe runs before the verdict it must not influence"
    after = src[probe_at:]
    assert "l2 =" not in after, "the grader probe reassigns the Layer-2 outcome"


def test_the_probe_always_purges_the_key_even_on_failure() -> None:
    """A diagnostic that reintroduces the leak is worse than no diagnostic — the purge is in a
    `finally`, so the exception path cannot leave the answer key behind."""
    import inspect

    from mosaera_core.bench import grader_probe

    src = inspect.getsource(grader_probe.grader_catches_a_mutation)
    assert "finally:" in src and src.index("finally:") < src.index("_purge_grader(ws)")
