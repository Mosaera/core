"""An arm names its model. It never inherits one.

QMB's first three sweeps measured `gpt-oss:20b` while the instance runs `qwen3.6:35b`, and nothing
looked wrong. `MOSAERA_HOME` defaults to the RELATIVE path `.mosaera`, so pointing the bench at a
scratch directory — which CLAUDE.md's live-data rule effectively requires — silently discarded
settings.json's role bindings and fell back to a default. A benchmark that cannot name the model it
tested cannot rank models.
"""

from __future__ import annotations

from typing import Any

import pytest
from mosaera_api import pmbench_run
from mosaera_api.pmbench_run import ArmModelMismatch, _pin, build_callables
from mosaera_core.config import Settings
from mosaera_core.config._settings import RoleModel


def _settings() -> Settings:
    return Settings.from_env()


def test_pinning_overrides_whatever_the_environment_resolved() -> None:
    """The fix for the trap: the arm's choice wins over ambient config."""
    pinned = _pin(_settings(), "some-model:7b")
    assert pinned.pm_model == "some-model:7b"
    assert pinned.role_providers["pm"] == "ollama"


def test_pinning_clears_cost_modes_that_would_shadow_the_arm() -> None:
    """`agents_bridge.py:321-331` clears these for the same reason: a cost-mode entry for "pm"
    supersedes `pm_model` (`_settings.py:462`), so without this the sweep would again test a model
    nobody asked for — the exact failure being fixed."""
    from dataclasses import replace

    shadowed = replace(
        _settings(),
        cost_modes={"balanced": {"pm": RoleModel(provider="ollama", model="other:1b")}},
        active_cost_mode="balanced",
    )
    pinned = _pin(shadowed, "wanted:7b")
    assert pinned.cost_modes == {}
    assert pinned.active_cost_mode is None


def test_no_model_means_inherit_which_is_what_a_plain_sweep_wants() -> None:
    base = _settings()
    assert _pin(base, None) is base


def test_a_model_the_provider_does_not_serve_is_refused_before_any_gpu_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo'd arm would otherwise run a whole sweep and report errors instead of a refusal.
    `init_chat_model` accepts any name; the failure surfaces only at call time."""
    monkeypatch.setattr(pmbench_run, "list_models", lambda s: ["real:7b", "other:3b"])
    with pytest.raises(ArmModelMismatch, match="not served by this provider"):
        build_callables(_settings(), "typo:7b")


def test_availability_is_read_BEFORE_pinning(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard was inert when first written. `list_models` unions the live provider list with the
    CONFIGURED role models, so consulting it after pinning put the very name under test into its own
    allowlist and nothing could ever be refused.

    Asserted by making `list_models` echo whatever `pm_model` it is handed: if the call happens
    after pinning, the typo is 'available' and no refusal is raised."""
    monkeypatch.setattr(pmbench_run, "list_models", lambda s: ["real:7b", s.pm_model])
    with pytest.raises(ArmModelMismatch):
        build_callables(_settings(), "typo:7b")


def test_a_resolved_model_that_differs_from_the_request_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Belt and braces: even if some future layer rewrites the binding, the run refuses rather than
    quietly reporting a number about a model nobody asked for."""

    class _Other:
        model = "something-else:1b"

    monkeypatch.setattr(pmbench_run, "list_models", lambda s: ["wanted:7b"])
    monkeypatch.setattr(pmbench_run, "get_chat_model", lambda role, s: _Other())
    with pytest.raises(ArmModelMismatch, match="resolved"):
        build_callables(_settings(), "wanted:7b")


def test_an_unpinned_run_is_not_refused_for_a_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--arm` is opt-in; a plain sweep still works and simply records what it got."""

    class _Any:
        model = "whatever:1b"

    monkeypatch.setattr(pmbench_run, "list_models", lambda s: ["whatever:1b"])
    monkeypatch.setattr(pmbench_run, "get_chat_model", lambda role, s: _Any())
    _propose, _validate, model_id = build_callables(_settings(), None)
    assert model_id == "whatever:1b"


def test_trials_are_keyed_so_two_arms_line_up_exactly() -> None:
    """Pairing is the whole economy of the design. A key must identify case, dimension and pass, so
    arm A's pass 3 of QMB-01/safe is compared against arm B's pass 3 of QMB-01/safe and nothing
    else."""
    from mosaera_core.pmbench.arms import compare_arms

    a: dict[tuple[str, str, int], bool] = {("QMB-01", "safe", i): True for i in range(3)}
    b: dict[tuple[str, str, int], bool] = {("QMB-01", "safe", i): False for i in range(3)}
    shifted: dict[tuple[str, str, int], bool] = {
        ("QMB-01", "safe", i + 99): False for i in range(3)
    }

    assert compare_arms("a", "b", a, b).discordant == 3
    assert compare_arms("a", "b", a, shifted).discordant == 0, "misaligned passes must not pair"


def _unused(_: Any) -> None:  # keeps the Any import honest for the type checker
    return None


# --- what a 43-minute comparison must leave behind ----------------------------------------------


def test_a_comparison_records_which_way_the_lean_ran() -> None:
    """McNemar is symmetric: 9/3 and 3/9 give the same p. The first real comparison printed only
    `p=0.146`, so the split could be recovered by inversion but its DIRECTION could not — the run
    could not say which model won the trials they disagreed on, which is the whole question."""
    from mosaera_core.pmbench.arms import compare_arms

    a: dict[tuple[str, str, int], bool] = {("QMB-01", "safe", i): True for i in range(9)}
    b: dict[tuple[str, str, int], bool] = {("QMB-01", "safe", i): False for i in range(9)}
    forward = compare_arms("A", "B", a, b)
    backward = compare_arms("A", "B", b, a)

    assert forward.p_value == backward.p_value, "the p-value alone cannot carry direction"
    assert (forward.a_only, forward.b_only) == (9, 0)
    assert (backward.a_only, backward.b_only) == (0, 9), "so the split must be recorded separately"


def test_a_comparison_keeps_the_trials_it_disagreed_on() -> None:
    """Only discordant trials decide a ranking, and they are the ones worth reading. The first
    comparison spent 43 minutes and kept nothing, so the claim it produced could not be checked
    against the proposals behind it — the step that has caught every defect in this suite."""
    from mosaera_api.pmbench_run import _disagreements

    a = {("QMB-01", "safe", 0): True, ("QMB-02", "honest", 1): False, ("QMB-03", "safe", 0): True}
    b = {("QMB-01", "safe", 0): False, ("QMB-02", "honest", 1): True, ("QMB-03", "safe", 0): True}

    rows = _disagreements(a, b, "model-a", "model-b")

    assert len(rows) == 2, "the trial both arms agreed on is not a disagreement"
    assert rows[0] == {"case": "QMB-01", "dimension": "safe", "pass": 0, "passed": "model-a"}
    assert rows[1] == {"case": "QMB-02", "dimension": "honest", "pass": 1, "passed": "model-b"}


def test_disagreements_name_the_model_that_passed_not_just_the_arm() -> None:
    """A row saying "arm A" is useless a week later; a row naming the model is evidence."""
    from mosaera_api.pmbench_run import _disagreements

    rows = _disagreements(
        {("QMB-01", "safe", 0): True}, {("QMB-01", "safe", 0): False}, "qwen3.6:35b", "gpt-oss:20b"
    )
    assert rows[0]["passed"] == "qwen3.6:35b"


# --- cost capture -------------------------------------------------------------------------------


def test_the_meter_is_attached_to_the_model_not_threaded_through_a_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`pm.chat` and `pm.curate_backlog` take no `RunnableConfig`, and adding one to production
    signatures to serve a benchmark would be the tail wagging the dog. A `BaseChatModel` carries its
    own `callbacks`, which LangChain merges at invoke time."""
    from mosaera_core.cost import CostMeter, UsageCallback

    class _Model:
        model = "wanted:7b"
        callbacks: Any = None

    captured = _Model()
    monkeypatch.setattr(pmbench_run, "list_models", lambda s: ["wanted:7b"])
    monkeypatch.setattr(pmbench_run, "get_chat_model", lambda role, s: captured)

    meter = CostMeter()
    build_callables(_settings(), "wanted:7b", meter)

    assert captured.callbacks is not None, "nothing would ever be metered"
    assert isinstance(captured.callbacks[0], UsageCallback)


def test_no_meter_means_no_callback_so_a_plain_sweep_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Model:
        model = "wanted:7b"
        callbacks: Any = None

    captured = _Model()
    monkeypatch.setattr(pmbench_run, "list_models", lambda s: ["wanted:7b"])
    monkeypatch.setattr(pmbench_run, "get_chat_model", lambda role, s: captured)

    build_callables(_settings(), "wanted:7b", None)
    assert captured.callbacks is None


def test_an_arms_metadata_carries_tokens_and_calls() -> None:
    """What a model comparison needs beside its verdict. Per-MODEL attribution is exact here;
    per-AGENT lands under "unknown" because `agent_for_node` needs a LangGraph node and a direct
    call has none — recorded rather than papered over."""
    from mosaera_core.cost import CostMeter, TokenUsage

    meter = CostMeter()
    meter.record("unknown", "wanted:7b", TokenUsage(input_tokens=100, output_tokens=20))
    rollup = meter.rollup()

    assert rollup["total_tokens"] == 120
    assert rollup["calls"] == 1
    assert rollup["by_model"][0]["model"] == "wanted:7b"
