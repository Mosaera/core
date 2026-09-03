"""Wire QMB to the REAL PM and the REAL changeset validator, and run a sweep.

Lives in `apps/api` because that is the only layer allowed to import both `mosaera_agents` (the PM)
and this app's validator; `core`, where the suite lives, may import neither
(`scripts/check_layer_imports.py`, whose three grandfathered crossings are a shrink-only ratchet).
The suite therefore takes them as callables — the inversion `intake_ask.run_intake_pass` already
uses, for the reason it states: "a harness wants the exception".

Two properties this module is responsible for, because they decide whether a QMB number means
anything at all:

1. **The real entry points.** `pm.chat` and `pm.curate_backlog` are called exactly as the product
   calls them, and the chat context comes from the real `build_pm_context`. A harness that
   assembled its own prompt would measure the harness.
2. **The model is recorded.** Model Substitutability means a QMB score is a statement about one
   model; a rate quoted without the model that produced it is not a result.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from mosaera_agents import pm
from mosaera_core.config import Settings
from mosaera_core.cost import CostMeter, UsageCallback
from mosaera_core.grounding_text import ground_named_files
from mosaera_core.models import get_chat_model, list_models
from mosaera_core.pmbench import (
    CaseObservation,
    PMResponse,
    QMBCase,
    compare_arms,
    compare_by_dimension,
    load_pm_case,
    run_pm_case,
    score_pm,
)
from mosaera_core.pmbench.harness import render_backlog_rows
from mosaera_core.tools.repo import describe_coder_capabilities

from mosaera_api.pm_sections import _render_backlog
from mosaera_api.projects import apply_backlog_changeset


class _FixtureStore:
    """The fixture as the store the validator expects. Reads only — nothing is ever written.

    Modelled on `govbench/store.py`: an in-memory stand-in keeps a bench off the live database,
    which is not a stylistic preference here (CLAUDE.md's live-data rule, and the ~2,500 scorecards
    that a test pointed at a real store once destroyed).
    """

    def __init__(self, case: QMBCase) -> None:
        self._rows = render_backlog_rows(case)

    def list_backlog_items(self, project_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows]

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - a write means a harness bug
        raise AssertionError(f"QMB fixture store is read-only; {name!r} would have mutated it")


def _code_evidence_for(case: QMBCase, text: str) -> str:
    """The fixture's file contents, selected and rendered by the PRODUCTION helper.

    The fixture is the reader — QMB has no clone, and `ground_named_files` takes an injected
    `read` for exactly that reason. A fixture that declares no `contents` yields "", so the arm
    sees the prompt it always saw and every pre-`contents` case is unchanged.
    """
    bodies = dict(case.contents)
    if not bodies:
        return ""
    return ground_named_files(text, case.files, lambda rel: bodies[rel])


def _context_for(case: QMBCase, settings: Settings) -> str:
    """The chat context, assembled by the real builder over the fixture."""
    from mosaera_api.pm_context_builder import build_pm_context, make_bundle_loader

    detail = {
        "id": "qmb",
        "name": case.id,
        "brief": case.brief,
        "source_repo": "https://gitlab.example/qmb/fixture.git",
        "backlog": render_backlog_rows(case),
        "runs": [],
        "has_gitlab_token": False,
    }
    built = build_pm_context(
        detail,
        [],
        [],
        [],
        make_bundle_loader(None, settings.uploads_dir),  # type: ignore[arg-type]
        user_message=case.prompt,
        repo_overview="## Files\n" + "\n".join(case.files),
        overview_current=True,
        on_gitlab=False,
    )
    return str(built.context)


class ArmModelMismatch(RuntimeError):
    """The run resolved a different model than the arm asked for. Refuse rather than report.

    Not hypothetical, and not a configuration error anyone made: `MOSAERA_HOME` defaults to the
    RELATIVE path `.mosaera` (`config/_from_env.py:31`), so pointing a bench at a scratch directory
    — which CLAUDE.md's live-data rule effectively requires — silently discards settings.json's
    role bindings and falls back to `Settings.pm_model`'s default. QMB's first three sweeps
    therefore measured `gpt-oss:20b` while the instance runs `qwen3.6:35b`, and the number looked
    perfectly ordinary. A benchmark that cannot name the model it tested cannot rank models, so an
    arm asserts its model instead of inheriting one.
    """


def _pin(settings: Settings, model: str | None, provider: str = "ollama") -> Settings:
    """Settings that resolve the PM role to exactly ``model``. ``None`` keeps ambient config.

    The canonical idiom (`agents_bridge.py:321-331`), including its precaution: `cost_modes` and
    `active_cost_mode` are cleared, because a cost-mode entry for "pm" would otherwise shadow the
    arm's own choice and the sweep would again test a model nobody asked for.
    """
    if model is None:
        return settings
    return replace(
        settings,
        role_providers={**settings.role_providers, "pm": provider},
        pm_model=model,
        cost_modes={},
        active_cost_mode=None,
    )


def build_callables(
    settings: Settings, model: str | None = None, meter: CostMeter | None = None
) -> tuple[Any, Any, str]:
    """``(propose, validate, model_id)`` — the two app-owned steps plus what produced them.

    ``meter`` collects token usage. It is attached to the MODEL rather than threaded through a
    `RunnableConfig`, because `pm.chat` and `pm.curate_backlog` take no config argument and adding
    one to production signatures to serve a benchmark would be the tail wagging the dog. A
    `BaseChatModel` carries its own `callbacks`, LangChain merges them at invoke time, and
    `robust_invoke` passes `config=None`, so nothing is overridden.

    Attribution lands under "unknown" — `agent_for_node` needs a LangGraph node and there is no
    graph here. That is honest: the per-AGENT breakdown is meaningless for a direct call, while the
    per-MODEL one, which is what a model comparison needs, is exact.
    """
    # Ask what the provider serves BEFORE pinning. `list_models` unions the live provider list with
    # the CONFIGURED role models, so consulting it after pinning would include the very name being
    # checked — a guard whose allowlist contains its own subject, which is the inert-control defect
    # this project keeps finding. Caught here only because a typo'd model sailed through.
    available = set(list_models(settings))
    settings = _pin(settings, model)
    chat_model = get_chat_model("pm", settings)
    model_id = (
        getattr(chat_model, "model", None) or getattr(chat_model, "model_name", None) or "unknown"
    )
    if model is not None and str(model_id) != model:
        raise ArmModelMismatch(f"arm asked for {model!r} but the run resolved {model_id!r}")
    # `init_chat_model` accepts any name and fails only at call time, so a typo'd arm would run and
    # report a sweep of errors rather than a refusal. Check before any GPU time is spent — the same
    # "verify at save time, not at first use" rule the GitLab credential path learned.
    if model is not None and available and model not in available:
        raise ArmModelMismatch(
            f"{model!r} is not served by this provider; have: {', '.join(sorted(available))}"
        )
    if meter is not None:
        chat_model.callbacks = [UsageCallback(meter)]
    capabilities = describe_coder_capabilities(
        settings.delete_tool_enabled, settings.coder_repl_enabled
    )

    def propose(case: QMBCase, path: str) -> PMResponse:
        if path == "chat":
            reply, ops, _charter, _clarify = pm.chat(
                chat_model,
                _context_for(case, settings),
                [],
                case.prompt,
                capabilities=capabilities,
            )
            return PMResponse(reply=reply, ops=tuple(ops))
        backlog_text = _render_backlog(render_backlog_rows(case))
        ops = pm.curate_backlog(
            chat_model,
            backlog_text,
            case.brief,
            case.prompt,
            capabilities=capabilities,
            code_evidence=_code_evidence_for(case, f"{backlog_text}\n{case.prompt}"),
        )
        return PMResponse(reply="", ops=tuple(ops))

    def validate(case: QMBCase, ops: tuple[dict[str, Any], ...]) -> str:
        """The REAL validator's verdict, in dry-run. Its refusal is the Safe oracle.

        Nothing is applied: the store raises on any write, so a validator that got as far as
        applying would fail loudly rather than silently mutating a fixture.
        """
        if not ops:
            return ""
        try:
            apply_backlog_changeset(_FixtureStore(case), "qmb", list(ops))  # type: ignore[arg-type]
        except ValueError as exc:
            return str(exc)
        except AssertionError:
            return ""  # validation passed; the write attempt is the fixture store's stop sign
        return ""

    return propose, validate, str(model_id)


def run_arm(
    case_ids: list[str], model: str | None, repeat: int
) -> tuple[dict[tuple[str, str, int], bool], dict[str, Any]]:
    """One arm: every case, every pass, one model. Returns paired trials plus its metadata.

    Trials are keyed ``(case_id, dimension, pass_index)`` so two arms line up EXACTLY — same case,
    same fixture, same pass. That pairing is what lets the comparison discard the trials both models
    agree on, which is the whole reason a ranking costs tens of trials rather than hundreds.
    """
    settings = Settings.from_env()
    # The operator's rate table, with on-box models marked shadow — the same rule the product
    # uses. A bare `CostMeter()` carries NO prices, so every arm reported $0.00 however the
    # instance was configured, which silently defeats half of what the bench is for: ranking
    # models for the PM role has to weigh quality AGAINST cost.
    meter = CostMeter.for_settings(settings)
    propose, validate, model_id = build_callables(settings, model, meter)
    cases = [load_pm_case(c) for c in case_ids]

    trials: dict[tuple[str, str, int], bool] = {}
    unusable: list[str] = []
    started = time.monotonic()
    for index in range(repeat):
        observations = [run_pm_case(c, propose, validate) for c in cases]
        score = score_pm(list(zip(cases, observations, strict=True)))
        unusable.extend(score.unusable)
        for case_id, dimension, ok in score.trials:
            trials[(case_id, dimension, index)] = ok
    rollup = meter.rollup()
    return trials, {
        "model": model_id,
        "requested": model,
        "repeat": repeat,
        "seconds": round(time.monotonic() - started, 1),
        "unusable": unusable,
        # Tokens, wall-clock and money per arm. `usd` is REAL spend (a hosted arm); `shadow_usd`
        # is the imputed cost of an on-box arm, so a local model and a hosted one can be compared
        # on price without an imaginary bill being reported as a real one.
        "tokens": rollup.get("total_tokens", 0),
        "input_tokens": rollup.get("input_tokens", 0),
        "output_tokens": rollup.get("output_tokens", 0),
        "cache_read": rollup.get("cache_read", 0),
        "usd": rollup.get("usd", 0.0),
        "shadow_usd": rollup.get("shadow_usd", 0.0),
        "calls": rollup.get("calls", 0),
    }


def _disagreements(
    a_trials: dict[tuple[str, str, int], bool],
    b_trials: dict[tuple[str, str, int], bool],
    arm_a: str,
    arm_b: str,
) -> list[dict[str, Any]]:
    """The individual trials the arms disagreed on — the only ones that decide a ranking.

    Kept because the first real comparison spent 43 minutes of GPU time and produced six lines of
    text with nothing to re-examine. Every instrument defect in this suite so far was found by
    reading raw output rather than a rate, and a comparison that discards its evidence cannot be
    audited at all.
    """
    return sorted(
        (
            {
                "case": case,
                "dimension": dimension,
                "pass": index,
                "passed": arm_a if a_trials[key] else arm_b,
            }
            for key in a_trials.keys() & b_trials.keys()
            if a_trials[key] != b_trials[key]
            for case, dimension, index in [key]
        ),
        key=lambda d: (str(d["case"]), str(d["dimension"]), int(d["pass"])),
    )


def run_comparison(
    case_ids: list[str],
    model_a: str,
    model_b: str | None,
    repeat: int,
    null_floor: int | None = None,
) -> dict[str, Any]:
    """Compare two models — or one model against ITSELF, which is the null control.

    ``model_b is None`` runs arm A's model twice. Whatever difference appears then is noise by
    construction, and it is the floor a real ranking has to clear. Measured every time rather than
    remembered: `compare_arms.py` warns that "a hardcoded number that silently ages is the defect
    this whole session kept finding".
    """
    null_control = model_b is None
    a_trials, a_meta = run_arm(case_ids, model_a, repeat)
    b_trials, b_meta = run_arm(case_ids, model_b or model_a, repeat)

    if null_control:
        # Run the SAME comparison the real thing uses. Its job is calibration: one model against
        # itself must come back with no winner. If it names one, the test is measuring something
        # systematic about the arms rather than about the models, and no ranking from it is safe.
        check = compare_arms(a_meta["model"], b_meta["model"], a_trials, b_trials)
        return {
            "kind": "null_control",
            "arms": [a_meta, b_meta],
            "discordant": check.discordant,
            "concordant": check.concordant,
            "split": [check.a_only, check.b_only],
            "p_value": check.p_value,
            "calibrated": check.winner is None,
            "note": (
                "one model against itself. The discordant COUNT is sampling noise and sizes how "
                "many trials a real difference needs; the SPLIT should be near even, and a winner "
                "here would mean the test is miscalibrated"
            ),
        }

    report = compare_by_dimension(
        a_meta["model"], b_meta["model"], a_trials, b_trials, null_floor=null_floor
    )
    comparison = report.pooled
    return {
        "kind": "comparison",
        "arms": [a_meta, b_meta],
        # The verdict comes from the PRE-REGISTERED primary dimension, not the pooled split. The
        # pooled figure is reported, and flagged when the dimensions disagree in direction, because
        # then it is the DIFFERENCE of two real leanings and summarises nothing.
        "winner": report.winner,
        "primary": report.primary,
        "heterogeneous": report.heterogeneous,
        "by_dimension": {
            dim: {
                "split": [c.a_only, c.b_only],
                "p_value": c.p_value,
                "winner": c.winner,
                "verdict": c.verdict,
            }
            for dim, c in report.by_dimension.items()
        },
        "verdict": comparison.verdict,
        "p_value": comparison.p_value,
        "discordant": comparison.discordant,
        "concordant": comparison.concordant,
        # WHICH way the lean ran. Recovering it by inverting a p-value is not possible — McNemar is
        # symmetric, so 9/3 and 3/9 give the same number, and the first comparison could not say
        # which model won the trials it disagreed on.
        "split": [comparison.a_only, comparison.b_only],
        "needed": comparison.needed,
        "notes": list(comparison.notes),
        "disagreements": _disagreements(a_trials, b_trials, a_meta["model"], b_meta["model"]),
    }


def _paired_counts(a: dict, b: dict) -> tuple[int, int, int]:
    a_only = b_only = concordant = 0
    for key in a.keys() & b.keys():
        if a[key] == b[key]:
            concordant += 1
        elif a[key]:
            a_only += 1
        else:
            b_only += 1
    return a_only, b_only, concordant


def run_sweep(case_ids: list[str], repeat: int = 1) -> dict[str, Any]:
    """Run the named cases `repeat` times and score each pass separately.

    Passes are scored SEPARATELY and reported as a spread rather than averaged into one number.
    The point of repeating is to expose run-to-run variance — a dimension whose spread is wider
    than the effect it is meant to detect is unusable, and averaging would hide exactly that.
    `docs/engineering-history` records 5.5 hours spent on an A/B whose effect was under its noise.
    """
    settings = Settings.from_env()
    propose, validate, model_id = build_callables(settings)
    cases = [load_pm_case(c) for c in case_ids]

    passes: list[dict[str, Any]] = []
    observations: list[list[CaseObservation]] = []
    for _ in range(repeat):
        obs = [run_pm_case(c, propose, validate) for c in cases]
        observations.append(obs)
        score = score_pm(list(zip(cases, obs, strict=True)))
        passes.append(
            {
                "dimensions": {n: asdict(d) for n, d in score.dimensions.items()},
                "rates": {n: score.rate(n) for n in score.dimensions},
                "unusable": list(score.unusable),
            }
        )
    return {
        "model": model_id,
        "cases": case_ids,
        "repeat": repeat,
        "passes": passes,
        "observations": [[asdict(o) for o in run] for run in observations],
    }


def write_sweep(result: dict[str, Any], home: Path, stamp: str) -> Path:
    """Persist a sweep OR a comparison. Both cost GPU time; both keep their raw observations."""
    out = home / "benchmarks" / "_pmbench"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{stamp}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return path
