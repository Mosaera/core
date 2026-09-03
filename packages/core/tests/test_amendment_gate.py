"""The escalation-gate amendment (ADR-0087, #65 / F63) — the authority, scope and one-shot rules.

A delivered test is currently unamendable, so the engine can only ADD and any item whose purpose is
to CHANGE behaviour deadlocks. The ESCALATE arm already asks the operator and then ignores the
answer: `supervise_node` ORs an oracle conflict into `give_up`. These tests pin the narrow path by
which a human's answer now reaches the deterministic guard — and, more importantly, every route by
which it must NOT.

The load-bearing property, stated once: the operator authorizes a SCOPE, the PROCTOR produces the
CONTENT, and the result is content-pinned in `proctor_edits`. The coder never touches the path.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mosaera_core.graph._amendment import (
    amendment_delta,
    amendment_instruction,
    amendment_offer,
    authorized_amendment,
)

_OUTPUT = (
    "FAILED tests/test_report.py::test_totals_two_lines - AssertionError\n1 failed, 4 passed\n"
)


def _state(**over: Any) -> dict[str, Any]:
    """A run parked on an oracle conflict: the failing test is baselined, so the coder may not
    touch it and re-planning cannot help."""
    base: dict[str, Any] = {
        "task": "collapse the summary onto one line",
        "plan": "p",
        "design": "d",
        # NOTE: no "acceptance" key — RunState has none. The criterion rides in `claims`.
        "test_output": _OUTPUT,
        "integrity_baseline": {"tests/test_report.py": "h"},
        "authored_tests": [],
        "coder_escalated": True,
    }
    base.update(over)
    return base


def _ctx(*, enabled: bool = True, tester: bool = True, root: Any = None) -> Any:
    # `workspace` is real since #127: the authorization delta captures the authorized paths'
    # PRISTINE source, because the amend pass re-executes and can no longer re-read it from disk.
    return SimpleNamespace(
        settings=SimpleNamespace(amendment_gate=enabled),
        agents=SimpleNamespace(tester_enabled=tester),
        workspace=SimpleNamespace(root=root if root is not None else Path("/nonexistent")),
    )


def _human(**over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"resolution": "human", "approve": False, "feedback": "requirement changed"}
    d.update(over)
    return d


# --- the offer: what the operator is shown -----------------------------------------------------


def test_the_offer_names_the_failing_test_not_just_the_file() -> None:
    """A path is the wrong grain to ask a human about — `test_report.py` may hold eight tests of
    which one contradicts the item. The node ids are what they actually judge."""
    offer = amendment_offer(_state())
    assert offer["paths"] == ["tests/test_report.py"]
    assert offer["tests"] == ["tests/test_report.py::test_totals_two_lines"]
    # The criterion comes from `claims`, not the `acceptance` key this fixture used to set.
    # That key does not exist in RunState, so this assertion USED to pass only because the fake
    # state invented it — a test pinning a fiction, while production showed an empty criterion
    # on the first live firing (F66). It now reads what the run actually carries.
    assert offer["criterion"] == ""


def test_a_run_with_nothing_blocking_is_offered_nothing() -> None:
    """Deny-by-default. A failing test the producer COULD have fixed means the code may simply be
    wrong, and this must never become a way to blame the tests for a real defect."""
    assert amendment_offer(_state(integrity_baseline={})) == {}


def test_a_collection_control_path_is_never_offered() -> None:
    """Round-2 FIX-NOW from #65, re-applied: a conftest drops requirements wholesale and the
    effect is invisible in any test file."""
    offer = amendment_offer(
        _state(
            test_output="FAILED tests/conftest.py::test_x - E\n",
            integrity_baseline={"tests/conftest.py": "h"},
        )
    )
    assert offer == {}


# --- the evidence the offer stands on (F70, #75) ------------------------------------------------
#
# The half that was missing, and the reason the defect shipped: every fixture above hardcodes
# `test_output`, so nothing exercised a run that had not validated. A coder HAND-RAISE routes
# `implement → capture → supervise` WITHOUT passing through `test`, so on that branch `test_output`
# is absent — and the offer was silently withheld on exactly the branch where the producer is
# saying a protected test blocks it. Measured live twice on 2026-08-07 (runs 20260807-194739-644d8f
# and 20260807-195038-936bdf), after ADR-0087 had already recorded it as a residual.


def _handraise(**over: Any) -> dict[str, Any]:
    """A first-iteration hand-raise: no `test_output`, because `test` never ran."""
    s = _state(**over)
    s.pop("test_output", None)
    return s


def test_a_run_that_has_not_validated_yet_is_offered_nothing() -> None:
    """Deny-by-default with NO evidence at all. Correct behaviour, and it was the whole defect —
    correct-looking silence is why this survived a 3-round red team."""
    assert amendment_offer(_handraise()) == {}


def test_the_coders_own_validation_carries_the_offer_when_the_engine_has_none() -> None:
    """THE #75 pin. `run_tests` takes no arguments and runs the engine's resolved plan in the
    sandbox, so the producer chose only WHEN it ran — the output is engine-owned evidence."""
    offer = amendment_offer(_handraise(coder_test_output=_OUTPUT))
    assert offer["paths"] == ["tests/test_report.py"]
    assert offer["tests"] == ["tests/test_report.py::test_totals_two_lines"]


def test_the_engines_own_validation_always_wins() -> None:
    """Precedence, asserted where the two DISAGREE — equal outputs would prove nothing. The
    fallback exists to cover an absence, never to override a real validation."""
    offer = amendment_offer(
        _state(
            coder_test_output="FAILED tests/test_other.py::test_z - E\n",
            integrity_baseline={"tests/test_report.py": "h", "tests/test_other.py": "h"},
        )
    )
    assert offer["paths"] == ["tests/test_report.py"]


def test_a_coder_owned_failure_still_disqualifies_through_the_fallback() -> None:
    """The subset rule is not relaxed by the new source. One failure the producer COULD have
    fixed means the code may simply be wrong, whichever run observed it."""
    mixed = _OUTPUT + "FAILED tests/test_new.py::test_a - AssertionError\n"
    assert amendment_offer(_handraise(coder_test_output=mixed)) == {}


def test_the_offer_is_withheld_on_a_run_that_already_tampered() -> None:
    """A run that weakened a protected test may not then be handed authorization to amend one —
    that would be the amendment gate laundering the thing it exists to prevent.
    `blocking_protected_tests` does not check `tests_modified`; only this does."""
    assert amendment_offer(_state(tests_modified=True)) == {}
    assert amendment_offer(_handraise(coder_test_output=_OUTPUT, tests_modified=True)) == {}


# --- #79: every absence names its rule, per branch ---------------------------------------------
#
# `amendable_withheld` explained exactly ONE absence out of five. The knob being off, the Proctor
# being off, a conftest-only blocker, and no validation output yet all reached the operator as
# blank space — at a gate whose entire purpose is to ask them a question. Four of this repo's
# measured findings are that shape (F61, F65, F69, F71), and the F71 fix covered one function and
# left seven. So these assert PER BRANCH, not once.


def _fields(state: dict[str, Any], **ctxkw: Any) -> dict[str, Any]:
    from mosaera_core.graph._amendment import escalation_amendment_fields

    return escalation_amendment_fields(state, _ctx(**ctxkw))


def test_the_knob_being_off_is_stated_not_blank() -> None:
    out = _fields(_state(), enabled=False)
    assert "amendable" not in out
    assert "switched off" in out["amendable_withheld"]


def test_no_proctor_is_stated_and_says_why_the_coder_cannot_stand_in() -> None:
    """The loudest of the silent cases: the authorization is structurally unhonourable, because
    the only other agent in the loop is the producer whose work the test judges."""
    out = _fields(_state(), tester=False)
    assert "amendable" not in out
    assert "Proctor is switched off" in out["amendable_withheld"]
    assert "own exam" in out["amendable_withheld"]


def test_a_tampering_run_is_still_told_about_the_integrity_guard() -> None:
    out = _fields(_state(tests_modified=True))
    assert "integrity guard" in out["amendable_withheld"]


def test_a_conftest_only_blocker_is_stated_not_blank() -> None:
    """The #65 round-2 rule, finally visible to the operator who ticked the box: human authority
    extends to a test's content, never to what gets collected."""
    out = _fields(
        _state(
            test_output="FAILED tests/conftest.py::test_x - E\n",
            integrity_baseline={"tests/conftest.py": "h"},
        )
    )
    assert "amendable" not in out
    assert "collection-control" in out["amendable_withheld"]
    assert "tests/conftest.py" in out["amendable_withheld"]


def test_a_run_that_has_not_validated_says_SO_rather_than_nothing() -> None:
    """The F70 branch's residual: the offer is correctly withheld with no evidence, and the
    operator could not tell that from "nothing qualifies"."""
    out = _fields(_handraise())
    assert "no validation output" in out["amendable_withheld"]


def test_a_coder_fixable_failure_says_the_code_may_simply_be_wrong() -> None:
    """Deny-by-default's most important case, and the one most worth explaining — the operator
    must not read it as "the tests are wrong"."""
    mixed = _OUTPUT + "FAILED tests/test_new.py::test_a - AssertionError\n"
    out = _fields(_state(test_output=mixed))
    assert "COULD fix" in out["amendable_withheld"]


def test_a_run_where_amendment_was_NEVER_in_play_says_nothing_at_all() -> None:
    """Not every silence is a defect. A no-progress escalation on a run with no protected tests
    was never reaching for this control, and a callout explaining an absent one is noise."""
    out = _fields(_state(integrity_baseline={}, authored_tests=[]))
    assert out == {}


def test_an_offer_never_carries_a_withheld_reason() -> None:
    """The two are mutually exclusive by construction — an offer AND an explanation of its absence
    on the same payload would be the drift F65 was about."""
    out = _fields(_state())
    assert out["amendable"]["paths"] == ["tests/test_report.py"]
    assert "amendable_withheld" not in out


# --- #79: the blocking classifier and its reason cannot disagree -------------------------------


def test_the_refusal_reason_is_non_empty_EXACTLY_when_nothing_blocks() -> None:
    """The anti-drift invariant, the same one `convertible_decline_reason` is pinned by. Both come
    from one classifier, so this asserts the construction rather than hoping two functions agree."""
    from mosaera_core.escalate_arm import blocking_protected_tests, blocking_refusal_reason

    cases = [
        _state(),  # qualifies
        _state(integrity_baseline={}, authored_tests=[]),  # nothing protected
        _handraise(),  # no output
        _state(test_output=_OUTPUT + "FAILED tests/other.py::t - E\n"),  # coder-owned failure
        _state(test_output="no pytest summary here at all"),  # unparseable
    ]
    for st in cases:
        blocked = blocking_protected_tests(st)
        reason = blocking_refusal_reason(st)
        assert bool(reason) == (not blocked), (st.get("test_output"), blocked, reason)


def test_each_refusal_branch_gives_a_DIFFERENT_reason() -> None:
    """Three distinguishable states used to be one empty tuple. If two collapse to the same
    sentence the operator is back where they started."""
    from mosaera_core.escalate_arm import blocking_refusal_reason

    reasons = {
        blocking_refusal_reason(_state(integrity_baseline={}, authored_tests=[])),
        blocking_refusal_reason(_handraise()),
        blocking_refusal_reason(_state(test_output=_OUTPUT + "FAILED tests/o.py::t - E\n")),
    }
    assert len(reasons) == 3


# --- authority: only a human, and only with a Proctor to do the work ---------------------------


def test_an_autonomous_resolution_authorizes_nothing() -> None:
    """The mirror of `_sanction`'s `actor == "human"` rule. If this ever passes something through,
    an unattended run can rewrite its own acceptance tests and ADR-0036 is retired in silence."""
    resume = {"resolution": "rescope", "authorize_tests": ["tests/test_report.py"]}
    assert authorized_amendment(_state(), resume, enabled=True, tester_enabled=True) == []


def test_the_knob_off_authorizes_nothing() -> None:
    resume = _human(authorize_tests=["tests/test_report.py"])
    assert authorized_amendment(_state(), resume, enabled=False, tester_enabled=True) == []


def test_no_proctor_means_no_amendment() -> None:
    """A hard precondition, not a preference: with the tester off there is no non-producer amender,
    so the only way to honour the authorization would be to hand the path to the coder. Fail
    closed — the run gives up exactly as it does today."""
    resume = _human(authorize_tests=["tests/test_report.py"])
    assert authorized_amendment(_state(), resume, enabled=True, tester_enabled=False) == []


def test_a_human_authorization_is_honoured() -> None:
    """The node id is preserved, NOT reduced to its path — that precision is what bounds the
    amendment to the test the operator actually chose (red-team R2 FIX-NOW)."""
    resume = _human(authorize_tests=["tests/test_report.py::test_totals_two_lines"])
    assert authorized_amendment(_state(), resume, enabled=True, tester_enabled=True) == [
        "tests/test_report.py::test_totals_two_lines"
    ]


# --- scope: the payload is never trusted -------------------------------------------------------


def test_naming_a_test_that_is_not_blocking_authorizes_nothing() -> None:
    """The released set is computed server-side as (named ∩ blocking), so an operator who is
    confused — or a payload that is hostile — cannot reach a test that is not in the way."""
    resume = _human(authorize_tests=["tests/test_other.py", "tests/test_report.py"])
    assert authorized_amendment(_state(), resume, enabled=True, tester_enabled=True) == [
        "tests/test_report.py"
    ]


def test_naming_a_conftest_authorizes_nothing() -> None:
    state = _state(
        test_output=_OUTPUT + "FAILED tests/conftest.py::test_c - E\n",
        integrity_baseline={"tests/test_report.py": "h", "tests/conftest.py": "h"},
    )
    resume = _human(authorize_tests=["tests/conftest.py"])
    assert authorized_amendment(state, resume, enabled=True, tester_enabled=True) == []


def test_a_malformed_payload_authorizes_nothing() -> None:
    for bad in ("tests/test_report.py", 42, None, {"a": 1}):
        resume = _human(authorize_tests=bad)
        assert authorized_amendment(_state(), resume, enabled=True, tester_enabled=True) == []


def test_a_path_traversal_style_name_authorizes_nothing() -> None:
    resume = _human(authorize_tests=["../tests/test_report.py", "/tests/test_report.py", ""])
    assert authorized_amendment(_state(), resume, enabled=True, tester_enabled=True) == []


# --- the delta: an authorization stops the give-up, and only then ------------------------------


def test_an_authorization_writes_a_one_shot_pending_amendment(tmp_path: Any) -> None:
    pristine = "def test_totals_two_lines():\n    assert len(render(rows)) == 2\n"
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_report.py").write_text(pristine, encoding="utf-8")
    delta = amendment_delta(
        _ctx(root=tmp_path),
        _state(),
        _human(authorize_tests=["tests/test_report.py"]),
        "requirement changed",
    )
    assert delta == {
        "pending_amendment": ["tests/test_report.py"],
        "amendment_reason": "requirement changed",
        # #127: captured HERE, at a return that commits, because the amend pass re-executes in
        # guided mode and its own disk read would already contain the first amendment.
        "amendment_before_sources": {"tests/test_report.py": pristine},
    }


def test_no_authorization_writes_nothing() -> None:
    """OFF must be byte-identical to today: an empty delta means `oracle_conflict` still forces
    give-up, which is the pre-ADR-0087 behaviour."""
    assert amendment_delta(_ctx(enabled=False), _state(), _human(), "") == {}
    assert amendment_delta(_ctx(), _state(), _human(), "") == {}


# --- constructional coder-blindness ------------------------------------------------------------


def test_the_amend_ask_is_built_from_the_spec_never_from_the_producer() -> None:
    """At escalation time the implementation exists on disk, so the Proctor's blindness cannot be
    TEMPORAL the way `_proctor_validate_repair`'s is. It is constructional instead: this string is
    assembled from the task/plan/design/criterion and the operator's reason, and from nothing the
    producer said or produced. Weaker than temporal blindness — but checkable, which prose is not.
    """
    state = _state(
        diff="--- a/cli.py\n+++ b/cli.py\n-    print(header)\n",
        coder_summary="I removed the header line as asked",
        test_output=_OUTPUT + "\nE   assert 1 == 2 SECRETLEAK\n",
        escalate_reason="the task conflicts with test_totals_two_lines SECRETLEAK",
        claims=[{"id": "c1", "text": "the summary prints a single combined line"}],
    )
    ask = amendment_instruction(state, ["tests/test_report.py"], "requirement changed")
    for leaked in ("SECRETLEAK", "I removed the header", "--- a/cli.py", "assert 1 == 2"):
        assert leaked not in ask
    # And it DOES carry what it is supposed to.
    assert "collapse the summary onto one line" in ask
    assert "the summary prints a single combined line" in ask
    assert "requirement changed" in ask
    assert "tests/test_report.py" in ask


# --- consumption: the Proctor amends, once, and the guard still pins the content ---------------


def _amend_ws(tmp_path: Any, content: str) -> Any:
    import subprocess

    from mosaera_core.tools.repo import Workspace

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_report.py").write_text(content, encoding="utf-8")
    # git-init: the integrity surface is git-sourced now and raises on a bare directory.
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True, capture_output=True)  # noqa: S607 — git from PATH, no shell; test fixture
    return Workspace(root=tmp_path, run_id="t", branch="b")


_DELIVERED = (
    "def test_totals_two_lines():\n"
    "    lines = render(rows)\n"
    "    assert len(lines) == 2\n"
    "\n"
    "def test_totals_are_currency():\n"
    "    assert render(rows)[0].endswith('.00')\n"
)


def _drive_consume(tmp_path: Any, amended_to: str, *, pending: list[str] | None = None) -> Any:
    from mosaera_core.graph._proctor_authoring import consume_amendment
    from mosaera_core.testintegrity import integrity_baseline

    ws = _amend_ws(tmp_path, _DELIVERED)
    baseline = integrity_baseline(ws)
    calls: list[str] = []

    def author(instruction: str, config: Any = None, corrections: Any = ()) -> None:
        calls.append(instruction)
        (tmp_path / "tests" / "test_report.py").write_text(amended_to, encoding="utf-8")

    protected: set[str] = set()
    ctx: Any = SimpleNamespace(
        workspace=ws,
        protected_tests=protected,
        agents=SimpleNamespace(author_tests=author, tester_enabled=True),
        settings=SimpleNamespace(amendment_gate=True),
    )
    state = _state(
        integrity_baseline=baseline,
        pending_amendment=(["tests/test_report.py"] if pending is None else pending),
        amendment_reason="the summary is now one line",
    )
    out = consume_amendment(ctx, state, None)  # type: ignore[arg-type]
    return ws, baseline, out, protected, calls


_AMENDED = (
    "def test_totals_two_lines():\n"
    "    lines = render(rows)\n"
    "    assert len(lines) == 1\n"
    "\n"
    "def test_totals_are_currency():\n"
    "    assert render(rows)[0].endswith('.00')\n"
)


# --- the SAME-RUN origin (F71) --------------------------------------------------------------
#
# `blocking_protected_tests` offers a blocking test from EITHER origin: a baselined path inherited
# from an earlier item, OR one the Proctor authored THIS run (`authored_tests`, pinned in
# `tests_baseline`). Every test above drives the first. The second was never exercised anywhere,
# and consumption did not handle it: `baseline_test_sources` read only `integrity_baseline`, so
# `_weakens` returned its "no pristine source" sentinel and the path was silently `continue`d —
# then the write parked the run as tampering. Measured live on run 20260807-204815-c76f7b, where an
# operator authorized an amendment, watched the Proctor make it, and the run ended `incomplete`.
#
# #87 passed only because it happened to amend a test DELIVERED BY AN EARLIER ITEM.


_TAUTOLOGY = (
    "def test_totals_two_lines():\n    assert True\n"
    "\ndef test_totals_are_currency():\n    assert True\n"
)
_GUTTED = "def test_totals_two_lines():\n    assert len(render(rows)) == 1\n"


def _drive_same_run(tmp_path: Any, amended_to: str, *, pending: list[str] | None = None) -> Any:
    """A test the Proctor authored THIS run: pinned in `tests_baseline`, absent from
    `integrity_baseline` — the origin the offer accepts and consumption used to refuse."""
    from mosaera_core.graph._proctor_authoring import consume_amendment
    from mosaera_core.tools.repo import hash_files

    ws = _amend_ws(tmp_path, _DELIVERED)
    rel = "tests/test_report.py"
    tests_baseline = hash_files(ws, [rel])

    def author(instruction: str, config: Any = None, corrections: Any = ()) -> None:
        (tmp_path / "tests" / "test_report.py").write_text(amended_to, encoding="utf-8")

    protected: set[str] = set()
    ctx: Any = SimpleNamespace(
        workspace=ws,
        protected_tests=protected,
        agents=SimpleNamespace(author_tests=author, tester_enabled=True),
        settings=SimpleNamespace(amendment_gate=True),
    )
    state = _state(
        integrity_baseline={},  # nothing inherited — this run authored it
        authored_tests=[rel],
        tests_baseline=tests_baseline,
        pending_amendment=([rel] if pending is None else pending),
        amendment_reason="the bar it encodes cannot be met",
    )
    return ws, tests_baseline, consume_amendment(ctx, state, None), protected  # type: ignore[arg-type]


def test_a_same_run_authored_test_can_be_amended(tmp_path: Any) -> None:
    """THE F71 pin. The offer accepts this origin, so consumption must too — an authorization the
    operator can grant and that then voids itself is worse than no offer at all."""
    from mosaera_core.tools.repo import hash_files

    ws, _, out, _ = _drive_same_run(tmp_path, _AMENDED)
    assert out["amended_tests"] == ["tests/test_report.py"]
    assert out["amendment_refusals"] == {}
    # Re-pinned in the RAW-BYTES space `tampered_files` reads — the guard that has no excuse
    # parameter, and therefore the one that parked the live run.
    assert (
        out["tests_baseline"]["tests/test_report.py"]
        == hash_files(ws, ["tests/test_report.py"])["tests/test_report.py"]
    )


def test_BOTH_guards_are_satisfied_by_a_same_run_amendment(tmp_path: Any) -> None:
    """The live failure in one assertion: two guards read two different hash spaces, and an
    amendment that satisfies only one still parks the run."""
    from mosaera_core.testintegrity import tampered_integrity
    from mosaera_core.tools.repo.diff import tampered_files

    ws, _, out, _ = _drive_same_run(tmp_path, _AMENDED)
    assert tampered_files(ws, out["tests_baseline"]) == []
    assert tampered_integrity(ws, {}, proctor_edits=out["proctor_edits"]) == []


def test_a_same_run_amendment_that_guts_the_unauthorized_test_is_refused(tmp_path: Any) -> None:
    """The collateral rule must bite IDENTICALLY for this origin — the whole risk of widening the
    mechanism is that the new path is weaker than the old one."""
    _, _, out, _ = _drive_same_run(tmp_path, _GUTTED)
    assert out["amended_tests"] == []
    assert "tests_baseline" not in out  # nothing re-pinned ⇒ the guard still trips
    assert "did not authorize" in out["amendment_refusals"]["tests/test_report.py"]


def test_a_same_run_amendment_to_a_tautology_is_refused(tmp_path: Any) -> None:
    _, _, out, _ = _drive_same_run(tmp_path, _TAUTOLOGY)
    assert out["amended_tests"] == []
    assert "assertion floor" in out["amendment_refusals"]["tests/test_report.py"]


def test_a_proctor_that_declines_a_same_run_path_sanctions_nothing(tmp_path: Any) -> None:
    _, _, out, _ = _drive_same_run(tmp_path, _DELIVERED)  # unchanged
    assert out["amended_tests"] == []
    assert "did not change the file" in out["amendment_refusals"]["tests/test_report.py"]


def test_a_later_write_at_an_amended_same_run_path_still_trips(tmp_path: Any) -> None:
    """One-shot, in the raw-bytes space. The re-pin excuses the AUTHORIZED content, not the path."""
    from mosaera_core.tools.repo.diff import tampered_files

    ws, _, out, _ = _drive_same_run(tmp_path, _AMENDED)
    (tmp_path / "tests" / "test_report.py").write_text("def test_x():\n    assert True\n", "utf-8")
    assert tampered_files(ws, out["tests_baseline"]) == ["tests/test_report.py"]


def test_the_coder_is_still_refused_on_an_amended_same_run_path(tmp_path: Any) -> None:
    _, _, _, protected = _drive_same_run(tmp_path, _AMENDED)
    assert "tests/test_report.py" in protected


def test_an_unauthorized_same_run_path_is_never_sanctioned(tmp_path: Any) -> None:
    """The server-side intersection still governs: naming a path the caller did not scope
    sanctions nothing, whatever the payload claimed."""
    _, _, out, _ = _drive_same_run(tmp_path, _AMENDED, pending=["tests/test_other.py"])
    assert out["amended_tests"] == []
    assert "tests_baseline" not in out


def test_a_path_pinned_by_BOTH_baselines_is_excused_in_both(tmp_path: Any) -> None:
    """#76 red team, round 1. Two guards read two hash spaces and neither sees the other's, so a
    path pinned in both must be recorded in both — never in whichever is convenient. Recording one
    is what parked the live run; recording "either" would leave the same hole behind a coin flip."""
    from mosaera_core.graph._proctor_authoring import consume_amendment
    from mosaera_core.testintegrity import integrity_baseline, tampered_integrity
    from mosaera_core.tools.repo import hash_files
    from mosaera_core.tools.repo.diff import tampered_files

    ws = _amend_ws(tmp_path, _DELIVERED)
    rel = "tests/test_report.py"

    def author(instruction: str, config: Any = None, corrections: Any = ()) -> None:
        (tmp_path / "tests" / "test_report.py").write_text(_AMENDED, encoding="utf-8")

    ctx: Any = SimpleNamespace(
        workspace=ws,
        protected_tests=set(),
        agents=SimpleNamespace(author_tests=author, tester_enabled=True),
        settings=SimpleNamespace(amendment_gate=True),
    )
    both: Any = _state(
        integrity_baseline=integrity_baseline(ws),
        authored_tests=[rel],
        tests_baseline=hash_files(ws, [rel]),
        pending_amendment=[rel],
        amendment_reason="r",
    )
    out = consume_amendment(ctx, both, None)
    assert out is not None
    assert out["amended_tests"] == [rel]
    assert rel in out["proctor_edits"] and rel in out["tests_baseline"]
    assert tampered_files(ws, out["tests_baseline"]) == []
    assert tampered_integrity(ws, {rel: "stale"}, proctor_edits=out["proctor_edits"]) == []


def test_a_path_pinned_by_NO_baseline_sanctions_nothing_and_says_why(tmp_path: Any) -> None:
    """#76 red team: the last line of the scope rule. A path nothing pins cannot be amended — and
    the original code fell through such a path silently, which is the defect being fixed."""
    from mosaera_core.graph._proctor_authoring import proctor_amend

    ws = _amend_ws(tmp_path, _DELIVERED)
    ctx: Any = SimpleNamespace(
        workspace=ws,
        protected_tests=set(),
        agents=SimpleNamespace(author_tests=lambda *a, **k: None, tester_enabled=True),
        settings=SimpleNamespace(amendment_gate=True),
    )
    unpinned: Any = _state(integrity_baseline={}, authored_tests=[], tests_baseline={})
    result = proctor_amend(ctx, unpinned, None, ["tests/test_report.py"], "r")
    assert result.amended() == []
    assert "not pinned by any baseline" in result.refused["tests/test_report.py"]


def test_an_amended_run_vouches_only_on_a_PROVEN_mutation_catch() -> None:
    """#76 red team, round 3 — FIX-NOW, and the more serious of the two.

    ADR-0087 names this rule as the BACKSTOP for its accepted semantic-weakening residual: *"a run
    with non-empty proctor_edits already vouches only on a PROVEN mutation catch, never on an
    unmeasured one."* A same-run amendment records in `tests_baseline`, NOT `proctor_edits` — so
    keying the tighter rule on `proctor_edits` alone let exactly the runs whose acceptance bar had
    just been renegotiated fall back to the LOOSER rule. Widening §5 to a second origin had quietly
    weakened the oracle posture for it.

    Asserted on the PREDICATE the gate consumes, not a copy of its logic.
    """
    from mosaera_core.graph._amendment import sanctioned_test_edit

    assert sanctioned_test_edit({}) is False  # no sanctioned edit ⇒ the standard rule
    assert sanctioned_test_edit({"proctor_edits": {"tests/a.py": "h"}}) is True
    assert sanctioned_test_edit({"amended_tests": ["tests/a.py"]}) is True  # THE new origin
    assert sanctioned_test_edit({"amended_tests": [], "proctor_edits": {}}) is False


def test_an_OPERATOR_sanctioned_edit_to_a_same_run_test_is_not_tampering(tmp_path: Any) -> None:
    """2026-08-07 audit, Class C: `operator_edits` reached `tampered_integrity` but never
    `tampered_files`, which takes no excuse parameter at all and hashes in the raw-bytes space.
    So a human write-gate approval of a change to a test the Proctor authored THIS run still
    parked the run as tampering — F71's defect, one origin over.

    Excused exactly as `tampered_integrity` excuses it: the content must hash to what the human
    approved, and a collection-control path is never excusable.
    """
    from mosaera_core.graph._tamper import _raw_tampered_less_sanctioned
    from mosaera_core.testintegrity import integrity_hash
    from mosaera_core.tools.repo import hash_files

    ws = _amend_ws(tmp_path, _DELIVERED)
    rel = "tests/test_report.py"
    baseline = hash_files(ws, [rel])
    ctx: Any = SimpleNamespace(workspace=ws)

    # The human approves a specific new content at the write gate.
    (tmp_path / "tests" / "test_report.py").write_text(_AMENDED, encoding="utf-8")
    approved = {rel: integrity_hash(ws, rel)}
    assert _raw_tampered_less_sanctioned(ctx, baseline, approved) == set()

    # Anything OTHER than the approved content still trips — the excuse is content-pinned.
    (tmp_path / "tests" / "test_report.py").write_text("def test_x():\n    assert True\n", "utf-8")
    assert _raw_tampered_less_sanctioned(ctx, baseline, approved) == {rel}

    # And with no approval at all, the guard behaves exactly as before.
    assert _raw_tampered_less_sanctioned(ctx, baseline, {}) == {rel}


def test_the_knob_flip_drop_CLEARS_the_previous_turns_refusals(tmp_path: Any) -> None:
    """#79. The knob-off branch returned no `amendment_refusals` key at all, so a run that had
    refusals recorded on an earlier turn showed them again here — attributed to this turn, which
    never ran a check. A stale reason is worse than no reason: it is a wrong one."""
    from mosaera_core.graph._proctor_authoring import consume_amendment

    ctx: Any = SimpleNamespace(
        workspace=_amend_ws(tmp_path, _DELIVERED),
        protected_tests=set(),
        agents=SimpleNamespace(author_tests=lambda *a, **k: None, tester_enabled=True),
        settings=SimpleNamespace(amendment_gate=False),  # flipped off between park and resume
    )
    stale: Any = _state(
        pending_amendment=["tests/test_report.py"],
        amendment_refusals={"tests/test_other.py": "a reason from an EARLIER turn"},
    )
    out = consume_amendment(ctx, stale, None)
    assert out is not None
    assert out["amended_tests"] == []
    assert "tests/test_other.py" not in out["amendment_refusals"]
    assert (
        "switched off between the park and the resume"
        in (out["amendment_refusals"]["tests/test_report.py"])
    )


def test_an_amendment_refusal_is_never_silent(tmp_path: Any) -> None:
    """The meta-defect, asserted per branch. F61, F65, F69 and F71 are one class: a control that
    declines invisibly. Every refusal path must name the rule that bit."""
    cases = [
        (_DELIVERED, "did not change the file"),
        (_TAUTOLOGY, "assertion floor"),
        (_GUTTED, "did not authorize"),
    ]
    for i, (content, expected) in enumerate(cases):
        case_dir = tmp_path / f"case{i}"
        case_dir.mkdir()
        _, _, out, _ = _drive_same_run(case_dir, content)
        reasons = out["amendment_refusals"]
        assert reasons, f"no reason recorded for: {expected}"
        assert expected in reasons["tests/test_report.py"], (expected, reasons)


def test_an_authorized_amendment_is_excused_by_the_existing_guard(tmp_path: Any) -> None:
    """The whole point. The operator authorized a scope, the Proctor produced content, and the
    tamper guard excuses it under the SAME content-pinned rule as any other sanctioned edit —
    `tampered_integrity` gained no parameter and `packages/policies` was not touched."""
    from mosaera_core.testintegrity import integrity_hash, tampered_integrity

    ws, baseline, out, _, _ = _drive_consume(tmp_path, _AMENDED)
    assert out["proctor_edits"] == {
        "tests/test_report.py": integrity_hash(ws, "tests/test_report.py")
    }
    assert out["amended_tests"] == ["tests/test_report.py"]
    assert tampered_integrity(ws, baseline, proctor_edits=out["proctor_edits"]) == []


def test_the_authorization_is_one_shot(tmp_path: Any) -> None:
    """Path-scoped and content-UNPINNED is the weakest excuse in this system, so it must not
    survive the node that consumes it — not into another fix iteration, not into a gate-deny
    re-plan, not through a rehydrate. A second amendment needs a second human."""
    _, _, out, _, _ = _drive_consume(tmp_path, _AMENDED)
    assert out["pending_amendment"] == []


def test_a_later_different_write_at_an_amended_path_still_trips(tmp_path: Any) -> None:
    """Content-pinning survives the amendment (#65 round 3). Authorizing ONE content does not
    open the path — the coder re-weakening afterwards is still tampering."""
    from mosaera_core.testintegrity import tampered_integrity

    ws, baseline, out, _, _ = _drive_consume(tmp_path, _AMENDED)
    (tmp_path / "tests" / "test_report.py").write_text(
        "def test_totals_two_lines():\n    assert True\n", encoding="utf-8"
    )
    assert tampered_integrity(ws, baseline, proctor_edits=out["proctor_edits"]) == [
        "tests/test_report.py"
    ]


def test_the_coder_is_still_refused_on_the_amended_path(tmp_path: Any) -> None:
    """The bar CHANGED; it was not released. `protected_tests` is the live set the coder's tools
    close over, and the amended path must be in it after the amendment as well as before."""
    _, _, _, protected, _ = _drive_consume(tmp_path, _AMENDED)
    assert "tests/test_report.py" in protected


def test_an_amendment_that_guts_the_unauthorized_test_is_refused(tmp_path: Any) -> None:
    """The within-file hole, closed by the assertion profile. The authorization is file-granular
    because the guard is, but `test_totals_are_currency` was never in the way and the operator
    never saw it named — so losing it refuses the whole amendment."""
    collateral = (
        "def test_totals_two_lines():\n    assert len(render(rows)) == 1\n"
        "\ndef test_totals_are_currency():\n    pass\n"
    )
    _, _, out, _, _ = _drive_consume(tmp_path, collateral)
    assert out["proctor_edits"] == {}


def test_an_amendment_that_deletes_the_other_test_is_refused(tmp_path: Any) -> None:
    only_one = "def test_totals_two_lines():\n    assert len(render(rows)) == 1\n"
    _, _, out, _, _ = _drive_consume(tmp_path, only_one)
    assert out["proctor_edits"] == {}


def test_an_emptied_file_is_refused(tmp_path: Any) -> None:
    """FN1, unconditional: emptying drops requirements wholesale. No authorization reaches it."""
    _, _, out, _, _ = _drive_consume(tmp_path, "")
    assert out["proctor_edits"] == {}


def test_an_amendment_to_a_tautology_is_refused(tmp_path: Any) -> None:
    gutted = (
        "def test_totals_two_lines():\n    assert True\n"
        "\ndef test_totals_are_currency():\n    assert True\n"
    )
    _, _, out, _, _ = _drive_consume(tmp_path, gutted)
    assert out["proctor_edits"] == {}


def test_a_proctor_that_declines_to_touch_the_file_sanctions_nothing(tmp_path: Any) -> None:
    _, _, out, _, _ = _drive_consume(tmp_path, _DELIVERED)
    assert out["proctor_edits"] == {}
    assert out["pending_amendment"] == []  # still consumed — no standing licence


def test_no_pending_amendment_is_a_no_op(tmp_path: Any) -> None:
    """`consume_amendment` returns None so `author_tests_node` falls through to its normal
    run-once path — the OFF case must be byte-identical."""
    _, _, out, _, calls = _drive_consume(tmp_path, _AMENDED, pending=[])
    assert out is None
    assert calls == []  # the Proctor was never invoked


# --- the operator's per-TEST choice bounds the damage (red-team R2 FIX-NOW) --------------------
#
# The authorization is granted per node id but the tamper guard works per FILE, and the first
# implementation reduced node ids to paths on the way in. Ticking ONE failing test therefore
# authorized weakening EVERY failing test in that file — the operator's choice, silently widened.


_TWO_FAILING = (
    "FAILED tests/test_report.py::test_totals_two_lines - AssertionError\n"
    "FAILED tests/test_report.py::test_totals_header - AssertionError\n"
    "2 failed\n"
)

_BOTH = (
    "def test_totals_two_lines():\n    assert len(render(rows)) == 2\n"
    "\ndef test_totals_header():\n"
    "    assert render(rows)[0] == 'Account  Total'\n"
    "    assert render(rows)[0].isupper()\n"
)


def _drive_two(tmp_path: Any, authorized: list[str], amended_to: str) -> dict[str, str]:
    from mosaera_core.graph._proctor_authoring import consume_amendment
    from mosaera_core.testintegrity import integrity_baseline

    ws = _amend_ws(tmp_path, _BOTH)
    baseline = integrity_baseline(ws)

    def author(instruction: str, config: Any = None, corrections: Any = ()) -> None:
        (tmp_path / "tests" / "test_report.py").write_text(amended_to, encoding="utf-8")

    ctx: Any = SimpleNamespace(
        workspace=ws,
        protected_tests=set(),
        agents=SimpleNamespace(author_tests=author, tester_enabled=True),
        settings=SimpleNamespace(amendment_gate=True),
    )
    state = _state(
        test_output=_TWO_FAILING,
        integrity_baseline=baseline,
        pending_amendment=authorized,
        amendment_reason="one line now",
    )
    out = consume_amendment(ctx, state, None)  # type: ignore[arg-type]
    assert out is not None
    return dict(out["proctor_edits"])


def test_authorizing_one_test_does_not_authorize_its_neighbour(tmp_path: Any) -> None:
    """The operator ticked `test_totals_two_lines`. Both tests were failing, so both were SHOWN —
    but only one was chosen, and the other must keep its full protection."""
    gutted_neighbour = (
        "def test_totals_two_lines():\n    assert len(render(rows)) == 1\n"
        "\ndef test_totals_header():\n    assert render(rows)[0] == 'Account  Total'\n"
    )
    edits = _drive_two(tmp_path, ["tests/test_report.py::test_totals_two_lines"], gutted_neighbour)
    assert edits == {}


def test_authorizing_one_test_still_lets_it_be_amended(tmp_path: Any) -> None:
    """The other half: the authorized test may change freely, including losing an assertion."""
    only_mine = (
        "def test_totals_two_lines():\n    assert len(render(rows)) == 1\n"
        "\ndef test_totals_header():\n"
        "    assert render(rows)[0] == 'Account  Total'\n"
        "    assert render(rows)[0].isupper()\n"
    )
    assert _drive_two(tmp_path, ["tests/test_report.py::test_totals_two_lines"], only_mine)


def test_authorizing_both_tests_permits_both(tmp_path: Any) -> None:
    both_amended = (
        "def test_totals_two_lines():\n    assert len(render(rows)) == 1\n"
        "\ndef test_totals_header():\n    assert render(rows)[0] == 'Account | Total'\n"
    )
    edits = _drive_two(
        tmp_path,
        [
            "tests/test_report.py::test_totals_two_lines",
            "tests/test_report.py::test_totals_header",
        ],
        both_amended,
    )
    assert edits


def test_a_bare_path_covers_the_failing_tests_but_not_a_passing_one(tmp_path: Any) -> None:
    """A bare path means "the tests that were in the way here", never "anything in this file". A
    test that was PASSING was never blocking, so no authorization reaches it."""
    from mosaera_core.graph._amendment import amended_functions

    state = _state(test_output=_TWO_FAILING)
    covered = amended_functions(["tests/test_report.py"], "tests/test_report.py", state)
    assert covered == {"test_totals_two_lines", "test_totals_header"}
    # One failing test only ⇒ the bare path covers only that one.
    single = _state(test_output=_OUTPUT)
    assert amended_functions(["tests/test_report.py"], "tests/test_report.py", single) == {
        "test_totals_two_lines"
    }


def test_turning_the_knob_off_between_park_and_resume_drops_the_authorization(
    tmp_path: Any,
) -> None:
    """Red-team R3. `Settings.from_env` re-reads per run, so a park that outlives a settings
    change resumes with the knob OFF and a live authorization in checkpointed state. "OFF is
    byte-identical" has to mean it — and the licence is CLEARED, not held for the knob's return."""
    from mosaera_core.graph._proctor_authoring import consume_amendment
    from mosaera_core.testintegrity import integrity_baseline

    ws = _amend_ws(tmp_path, _DELIVERED)
    called: list[str] = []

    def author(instruction: str, config: Any = None, corrections: Any = ()) -> None:
        called.append(instruction)

    ctx: Any = SimpleNamespace(
        workspace=ws,
        protected_tests=set(),
        agents=SimpleNamespace(author_tests=author, tester_enabled=True),
        settings=SimpleNamespace(amendment_gate=False),  # flipped off while parked
    )
    state = _state(
        integrity_baseline=integrity_baseline(ws),
        pending_amendment=["tests/test_report.py::test_totals_two_lines"],
        amendment_reason="r",
    )
    out = consume_amendment(ctx, state, None)  # type: ignore[arg-type]
    assert out is not None
    # The R3 property, asserted as a PROPERTY rather than an exact dict: the licence is consumed,
    # nothing is sanctioned, and the Proctor never ran. The return also carries the refusal reason
    # now (#79) — a dict-equality assertion would have made "explain why" look like a regression.
    assert out["pending_amendment"] == []
    assert out["amended_tests"] == []
    assert "proctor_edits" not in out and "tests_baseline" not in out
    assert called == []  # the Proctor was never invoked


# --- the offer says WHAT the item asked for, and WHO owns the bar (F66 + ADR-0087 §1-§4) -------
#
# On its first live firing the offer's `criterion` came through EMPTY: `amendment_offer` read
# `state["acceptance"]`, which is not a RunState key and never has been. The operator was asked to
# authorize amending three delivered tests without being told what the item wanted — precisely the
# context needed to tell a requirement change from a regression.


def _state_with_claims() -> dict[str, Any]:
    return _state(
        claims=[
            {"id": "87-c1", "text": "status with no --month reports ONLY the current month"},
            {"id": "87-c2", "text": "the empty-month fallback must be removed"},
        ]
    )


def test_the_criterion_comes_from_the_claims_not_a_missing_key() -> None:
    offer = amendment_offer(_state_with_claims())
    assert "current month" in offer["criterion"]
    assert "fallback must be removed" in offer["criterion"]


def test_a_run_with_no_claims_has_an_empty_criterion_not_a_guess() -> None:
    """Headless/CLI runs carry no structured acceptance. Empty is honest; invented is not."""
    assert amendment_offer(_state())["criterion"] == ""


class _Mem:
    def __init__(self, rows: dict[str, Any]) -> None:
        self._rows = rows
        self.asked: list[list[str]] = []

    def latest_test_contracts(self, project_id: str, paths: list[str]) -> dict[str, Any]:
        self.asked.append(list(paths))
        return {p: r for p, r in self._rows.items() if p in paths}


def _ctx_with(mem: Any, project_id: str | None = "proj-1") -> Any:
    return SimpleNamespace(memory=mem, project_id=project_id)


def test_the_offer_names_who_owns_the_blocking_bar() -> None:
    mem = _Mem(
        {
            "tests/test_report.py": {
                "owner_item_id": 42,
                "version": 2,
                "criterion": "the summary prints one line per account",
                "amended_from_version": 1,
            }
        }
    )
    offer = amendment_offer(_state_with_claims(), _ctx_with(mem))
    got = offer["contracts"]["tests/test_report.py"]
    assert got["owner_item_id"] == 42
    assert got["version"] == 2
    assert got["amended_before"] is True  # this bar has been renegotiated before — say so


def test_an_unregistered_path_gets_NO_contract_annotation() -> None:
    """The never-invent-ownership rule at the display layer. A missing row means the owner is
    unknown — a brownfield repo's human-authored tests are all like this — and the offer must
    show nothing rather than attribute the bar to whichever item last touched the file."""
    offer = amendment_offer(_state_with_claims(), _ctx_with(_Mem({})))
    assert "contracts" not in offer


def test_a_memory_failure_never_stops_the_gate_from_ASKING() -> None:
    """A run that cannot park because a lookup failed is worse than one that parks with less
    context. Every enrichment degrades to absent, never to an exception."""

    class _Broken:
        def latest_test_contracts(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise RuntimeError("db is down")

    offer = amendment_offer(_state_with_claims(), _ctx_with(_Broken()))
    assert offer["tests"]  # the question still gets asked
    assert "contracts" not in offer


def test_no_memory_or_no_project_is_simply_unannotated() -> None:
    assert "contracts" not in amendment_offer(_state_with_claims(), _ctx_with(None))
    assert "contracts" not in amendment_offer(_state_with_claims(), _ctx_with(_Mem({}), None))


def test_the_registry_is_only_asked_about_BLOCKING_paths() -> None:
    """Not the whole suite: the lookup is scoped to what is actually in the way."""
    mem = _Mem({})
    amendment_offer(_state_with_claims(), _ctx_with(mem))
    assert mem.asked == [["tests/test_report.py"]]


# --- the guided-mode REPLAY (#127) --------------------------------------------------------------
#
# `consume_amendment` sits above `author_tests_node`'s run-once guard and INSTEAD of it, and it
# clears `pending_amendment` in its own return. In guided mode the Proctor's write gate interrupts
# INSIDE the node, so the node never returns, the clear never commits, and LangGraph replays the
# node from the top with the authorization still standing — F35's mechanism, one function over.
# Measured live 2026-08-28 (run 20260828-202022-5a07ae): the same paths re-amended round after
# round, `iteration` frozen at 4, 1.29M -> 1.82M tokens on a one-line change.
#
# The old one-shot test asserts the RETURN clears the key. That is true and always will be; it
# proves the clear is written, never that it commits. These drive the replay instead.


def _replay_state(baseline: Any, before_sources: dict[str, str]) -> Any:
    """The state a replay re-enters with: the authorization still standing, because the return that
    would have cleared it never committed."""
    return _state(
        integrity_baseline=baseline,
        pending_amendment=["tests/test_report.py"],
        amendment_reason="the summary is now one line",
        amendment_before_sources=before_sources,
    )


def test_a_replay_does_not_re_ask_the_proctor_for_an_already_amended_path(tmp_path: Any) -> None:
    """The unbounded loop, closed. A path that already differs from its baseline was written by an
    earlier replay, so the second entry must not ask for it again — otherwise every operator
    approval buys one more Proctor pass over the same file, for ever."""
    from mosaera_core.graph._proctor_authoring import consume_amendment
    from mosaera_core.testintegrity import integrity_baseline

    ws = _amend_ws(tmp_path, _DELIVERED)
    baseline = integrity_baseline(ws)
    calls: list[str] = []

    def author(instruction: str, config: Any = None, corrections: Any = ()) -> None:
        calls.append(instruction)
        (tmp_path / "tests" / "test_report.py").write_text(_AMENDED, encoding="utf-8")

    ctx: Any = SimpleNamespace(
        workspace=ws,
        protected_tests=set(),
        agents=SimpleNamespace(author_tests=author, tester_enabled=True),
        settings=SimpleNamespace(amendment_gate=True),
    )
    state = _replay_state(baseline, {"tests/test_report.py": _DELIVERED})

    first = consume_amendment(ctx, state, None)  # type: ignore[arg-type]
    assert len(calls) == 1, "the first entry must ask the Proctor"
    assert first is not None and first["amended_tests"] == ["tests/test_report.py"]

    # The gate interrupted, so `first` never committed: the replay re-enters with the SAME state.
    second = consume_amendment(ctx, state, None)  # type: ignore[arg-type]
    assert len(calls) == 1, "the replay must NOT re-ask for a path already amended on disk"
    assert second is not None and second["pending_amendment"] == []


def test_a_replay_measures_collateral_damage_against_the_true_pristine_source(
    tmp_path: Any,
) -> None:
    """The laundering route, closed. `before_sources` used to be re-read from disk inside the amend
    pass; on a replay that read already contained the previous amendment, so a test function
    dropped in an earlier round was invisible to the collateral rule and got sanctioned. Anchored
    at the authorization, the removal is still measured against the ORIGINAL and refused."""
    from mosaera_core.graph._proctor_authoring import consume_amendment
    from mosaera_core.testintegrity import integrity_baseline

    ws = _amend_ws(tmp_path, _DELIVERED)
    baseline = integrity_baseline(ws)
    # A replay whose disk state has ALREADY lost `test_totals_are_currency` — the function the
    # operator never authorized. Re-reading disk here would see a one-function file and find
    # nothing removed; the anchor still holds the two-function original.
    dropped = "def test_totals_two_lines():\n    assert len(render(rows)) == 1\n"
    (tmp_path / "tests" / "test_report.py").write_text(dropped, encoding="utf-8")

    ctx: Any = SimpleNamespace(
        workspace=ws,
        protected_tests=set(),
        agents=SimpleNamespace(
            author_tests=lambda *a, **k: None,  # already written by the lost round
            tester_enabled=True,
        ),
        settings=SimpleNamespace(amendment_gate=True),
    )
    state = _replay_state(baseline, {"tests/test_report.py": _DELIVERED})

    out = consume_amendment(ctx, state, None)  # type: ignore[arg-type]
    assert out is not None
    assert out["proctor_edits"] == {}, "a removal the operator never authorized must not sanction"
    assert "tests/test_report.py" in out["amendment_refusals"]


def test_a_tampered_run_cannot_consume_an_authorization(tmp_path: Any) -> None:
    """Red-team of #127's own fix. `amendment_offer` already withholds on `tests_modified`, but
    `consume_amendment` did not check it. That was cushioned while every entry re-asked the Proctor
    (its write overwrote whatever was on disk); since #127 a path already differing from its
    baseline is NOT re-asked and is validated as it stands — so a protected test modified outside
    the sanctioned channel could be sanctioned as though the Proctor authored it. The producer
    editing its own exam is the one thing ADR-0087 exists to prevent."""
    from mosaera_core.graph._proctor_authoring import consume_amendment
    from mosaera_core.testintegrity import integrity_baseline

    ws = _amend_ws(tmp_path, _DELIVERED)
    baseline = integrity_baseline(ws)
    calls: list[str] = []
    # Someone other than the Proctor already changed the file, and the guard recorded it. The
    # content is deliberately a WELL-FORMED amendment (`_AMENDED` — the exact bytes the sanctioned
    # path accepts elsewhere in this file), so nothing else refuses it: not the assertion floor,
    # not the collateral rule. If this run is refused, it is because of `tests_modified` and
    # nothing else. An earlier draft used `assert True` here and passed with the guard REMOVED,
    # because the assertion floor caught it instead — green for the wrong reason.
    (tmp_path / "tests" / "test_report.py").write_text(_AMENDED, encoding="utf-8")

    ctx: Any = SimpleNamespace(
        workspace=ws,
        protected_tests=set(),
        agents=SimpleNamespace(
            author_tests=lambda *a, **k: calls.append("asked"), tester_enabled=True
        ),
        settings=SimpleNamespace(amendment_gate=True),
    )
    state = _state(
        integrity_baseline=baseline,
        pending_amendment=["tests/test_report.py"],
        amendment_reason="the summary is now one line",
        amendment_before_sources={"tests/test_report.py": _DELIVERED},
        tests_modified=True,
    )

    out = consume_amendment(ctx, state, None)  # type: ignore[arg-type]
    assert out is not None
    assert out.get("proctor_edits", {}) == {}, "nothing may be excused"
    assert out["amended_tests"] == [], "a tampered run must sanction nothing"
    assert out["pending_amendment"] == [], "and the licence must not be held for later"
    assert "tests/test_report.py" in out["amendment_refusals"]
    assert calls == [], "the Proctor must not even be asked"
