"""Bridge from a finished run's state to durable memory.

Kept in core (not mosaera_memory) because it needs the model gateway to embed
artifacts. All writes are best-effort: a memory backend problem must never crash
or fail a run, so failures are caught and surfaced as a warning.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from mosaera_memory import MemoryStore

import mosaera_core
from mosaera_core.config import Settings
from mosaera_core.models import get_embeddings
from mosaera_core.testintegrity import is_collection_control


def _embed(settings: Settings, text: str) -> list[float] | None:
    """Embed ``text`` for semantic retrieval — **currently unused, and deliberately so.**

    Every delivered run used to pay two of these round-trips to populate `Artifact.embedding`, and
    the only readers, `similar_artifacts` and `similar_doctrine`, have ZERO production callers (the
    sole reference in the tree is one store test). Cross-run retrieval is DIRECTION (ADR-0084), not
    built, so the cost bought nothing.

    Kept, with its callers removed, because the column and the store methods are the seam that
    DIRECTION will use — deleting them would be scope creep in the other direction. Re-enabling is
    passing this back in at the two `add_artifact` sites.

    A second reason the calls had to go: `get_embeddings` (`models.py`) is hard-wired to Ollama and
    ignores `role_providers` entirely, so on a box without Ollama — the hosted-API case — every
    delivered run silently paid a failing round-trip that this `except` swallowed.
    """
    try:
        return get_embeddings(settings).embed_query(text)
    except Exception:
        return None


def claim_rows(claims: list[Any], dispositions: list[Any] | None) -> list[dict[str, Any]]:
    """Join a run's claims with their evaluated verdicts into ledger rows.

    A claim the gate visit never evaluated (e.g. a crash before the gate) is honestly
    ``unevaluable``, not silently satisfied. Shared by the normal persist path and the
    ADR-0078 never-resumed-park capture in the API runner.
    """
    verdicts = {str(d.get("claim_id")): d for d in (dispositions or []) if isinstance(d, dict)}
    rows = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        disp = verdicts.get(str(c.get("id")), {})
        rows.append(
            {
                **c,
                "claim_id": str(c.get("id") or ""),
                "verdict": str(disp.get("verdict") or "unevaluable"),
                "oracle_ref": str(disp.get("oracle_ref") or ""),
            }
        )
    return rows


def receipt_json(state: dict[str, Any]) -> str | None:
    """The durable delivery receipt (ADR-0071 amendment) as a JSON decision payload.

    Everything the human's approval priced — gate verdict, oracle vouch, the named
    residual, the mutation tri-state — in one machine-readable row. ``None`` values
    survive as JSON ``null`` (tri-state honesty: never coerce "not measured" into a
    pass or a fail). Returns None when the run never carried a gate decision.
    """
    gate = state.get("gate_decision")
    if not isinstance(gate, dict):
        return None
    return json.dumps(
        {
            "action": gate.get("action", ""),
            "reasons": [str(r) for r in gate.get("reasons", [])],
            "reviewer_verdict": gate.get("reviewer_verdict", ""),
            "tests_passed": gate.get("tests_passed"),
            "oracle_verified": gate.get("oracle_verified"),
            "validation_strength": gate.get("validation_strength", "unknown"),
            "unsatisfied_claims": [str(c) for c in gate.get("unsatisfied_claims", [])],
            "human_override": bool(gate.get("human_override")),
            "oracle_vouched_by": gate.get("oracle_vouched_by", ""),
            "oracle_legs": gate.get("oracle_legs") or {},
            "oracle_residual": gate.get("oracle_residual", ""),
            "tests_mutation_caught": gate.get("tests_mutation_caught"),
        }
    )


def make_receipt_id(run_id: str, commit_sha: str, engine_version: str, receipt_payload: str) -> str:
    """The sealed receipt id (#63): a deterministic sha256 over the facts the receipt
    stands on, so anyone can independently re-derive it from the durable record —
    the seal is verifiable, never a database surrogate."""
    material = f"{run_id}\n{commit_sha}\n{engine_version}\n{receipt_payload}"
    return hashlib.sha256(material.encode()).hexdigest()


def _criterion_text(state: dict[str, Any], cap: int = 2_000) -> str:
    """The item's acceptance, from the claims the run was launched with.

    NOT `state["acceptance"]` — that key does not exist, which is why the amendment offer showed
    an empty criterion on its first live firing (F66). The claims ARE the acceptance, minted from
    it at launch, so they are the honest source. Empty when a run carries none (headless/CLI).
    """
    texts = [
        str(c.get("text", "")).strip()
        for c in (state.get("claims") or [])
        if isinstance(c, dict) and str(c.get("text", "")).strip()
    ]
    return "\n".join(texts)[:cap]


def _record_contracts(
    memory: MemoryStore,
    state: dict[str, Any],
    run_id: str,
    project_id: str | None,
    item_id: int | None,
    commit_sha: str,
    workspace_root: Any,
) -> None:
    """Register the test contracts this run DELIVERED or AMENDED (ADR-0087 §1-§4).

    Only on a real delivery: a parked run delivered no contract, and writing one would claim
    ownership of a bar that never shipped. No project (a CLI/ad-hoc run) ⇒ nothing to own.

    **Never invent ownership.** Rows are written ONLY for paths this run demonstrably authored
    (`authored_tests`, minus anything that was already baselined — the authoring-collision case)
    or amended (`amended_tests`). A pre-existing path this run merely ran against gets no row, so
    its absence keeps meaning "we do not know who wrote this", which is the truth.
    """
    if not project_id or not commit_sha or not state.get("approved"):
        return
    # Every failure here is swallowed, deliberately and separately from persist_run's outer
    # guard. That guard wraps the WHOLE body, and this call sits mid-way: an exception would
    # skip the gate decision, the receipt, the test results, the claims AND the final
    # `record_run` status flip, leaving a delivered run stuck in its interim state. A brand-new
    # subsystem must not be able to corrupt the record that predates it — most concretely when
    # `test_contracts` does not exist yet because a deploy skipped `make db-migrate`.
    try:
        _write_contracts(memory, state, run_id, project_id, item_id, workspace_root)
    except Exception as exc:  # pragma: no cover - defensive
        import warnings

        warnings.warn(f"test-contract registry write failed: {exc}", stacklevel=2)


def _write_contracts(
    memory: MemoryStore,
    state: dict[str, Any],
    run_id: str,
    project_id: str,
    item_id: int | None,
    workspace_root: Any,
) -> None:
    """The registry write itself — see ``_record_contracts`` for the guarantees."""
    baselined = set(state.get("integrity_baseline") or {})
    amended = [str(p) for p in (state.get("amended_tests") or [])]
    # `authored_tests` rides the PROTECTION set, which is wider than the baseline on purpose, so a
    # pre-existing `tests/helpers.py` is absent from `baselined` and would be registered as
    # `delivered` — the engine claiming first authorship of a human's file. A test CONTRACT is about
    # a test, so non-tests are simply not registry material.
    authored = [
        str(p)
        for p in (state.get("authored_tests") or [])
        # `is_test_file` here is pytest's DEFAULT naming and dropped every authored test on a
        # `python_files` repo, so no contract row was ever written for them.
        if str(p) not in baselined and not is_collection_control(str(p))
    ]
    criterion = _criterion_text(state)
    reason = str(state.get("amendment_reason") or "")
    profiles = _assertion_profiles(workspace_root, set(authored) | set(amended))
    pins = {**(state.get("tests_baseline") or {}), **(state.get("proctor_edits") or {})}
    for path in sorted(set(authored) | set(amended)):
        # An AMENDMENT renegotiates a bar that already existed — so it must have been baselined.
        # A path the Proctor both authored and amended within THIS run is new to the project
        # whatever happened to it mid-run: version 1, a delivery. Recording it as an amendment
        # would claim a prior version that was never delivered, and (before the fix below) with an
        # EMPTY content hash, because `proctor_edits` only ever holds baselined paths. #76 red
        # team round 2 — item 88 produces exactly this shape, so it would have corrupted the
        # registry's first real rows.
        is_amendment = path in amended and path in baselined
        memory.record_test_contract(
            project_id,
            path,
            provenance="amended" if is_amendment else "delivered",
            owner_item_id=item_id,
            owner_run_id=run_id,
            # Whichever space pinned it — `proctor_edits` for a baselined path, `tests_baseline`
            # for one authored this run. An unpinned contract row is a bar with no content behind
            # it, which is exactly what the registry exists to prevent.
            content_hash=str(pins.get(path, "")),
            criterion=criterion,
            # Only a HUMAN can authorize an amendment today (ADR-0087 §5); the Proctor writes the
            # content but never grants the permission.
            authorized_by="human" if is_amendment else None,
            amend_reason=reason if is_amendment else "",
            assertion_profile=profiles.get(path, {}),
        )


def _assertion_profiles(workspace_root: Any, paths: set[str]) -> dict[str, dict[str, int]]:
    """Per-function assertion counts for each path, read off the DELIVERED tree.

    Makes a weakening auditable ACROSS runs, which the per-run check cannot do: the in-run guard
    compares this run's before/after, and only a stored profile can answer "has this bar been
    quietly eroded over five items?".
    """
    from pathlib import Path

    from mosaera_core.oraclecheck import assertion_profile

    # Passed in, NOT read off state: `workspace_root` is not a RunState key, and reading one
    # that does not exist is exactly how F66 shipped an always-empty criterion.
    if not workspace_root:
        return {}
    out: dict[str, dict[str, int]] = {}
    for path in paths:
        try:
            prof = assertion_profile(Path(str(workspace_root), path).read_text(encoding="utf-8"))
        except OSError:
            continue
        if prof is not None:
            out[path] = prof
    return out


def persist_run(
    memory: MemoryStore,
    settings: Settings,
    run_id: str,
    *,
    source: str,
    branch: str,
    state: dict[str, Any],
    commit_sha: str,
    project_id: str | None = None,
    item_id: int | None = None,
    workspace_root: Any = None,
) -> None:
    """Persist a completed run and its artifacts. Best-effort; warns on failure.

    Evidence is written BEFORE the final APPROVED/NOT APPROVED status so a mid-write
    failure can't leave a durable "approved with no diff/tests" record: ensure_run
    only stubs the row (interim status) for the FK, and record_run flips it to the
    final status LAST, once the evidence is in.
    """
    try:
        memory.ensure_run(run_id, source=source, branch=branch, task=state.get("task", ""))
        if state.get("plan"):
            memory.add_decision(run_id, "plan", state["plan"])
        if state.get("design"):
            memory.add_decision(run_id, "design", state["design"])
        if state.get("coder_summary"):
            memory.add_decision(run_id, "summary", state["coder_summary"])
        if state.get("review"):
            memory.add_decision(run_id, "review", state["review"])
        if state.get("quality"):
            # Advisory code-quality of the change (JSON QualityScore); display-only.
            memory.add_decision(run_id, "quality", state["quality"])
        for note in state.get("quality_revise_log", []):
            # Trail of targeted quality revises (Phase 2), for the evidence log / ring.
            memory.add_decision(run_id, "quality_revise", note)
        for note in state.get("review_revise_log", []):
            # Trail of targeted reviewer-fix revises, for the evidence log.
            memory.add_decision(run_id, "review_revise", note)
        for note in state.get("hygiene_fix_log", []):
            # Trail of in-loop hygiene fixes (format/lint/types), for the evidence log.
            memory.add_decision(run_id, "hygiene_fix", note)
        if state.get("stalled") and state.get("stall_reason"):
            # Honest capability outcome: the run couldn't converge (no-progress breaker).
            memory.add_decision(run_id, "capability_limit", str(state["stall_reason"]))
        if state.get("plan_fallback_evidence"):
            # What the planner's model ACTUALLY returned when the engine substituted a fallback
            # (#71, F39) — both channels, done_reason, token counts. Written whenever it exists,
            # including on runs that went on to deliver: a fallback plan that a run recovered from
            # is still the engine discarding model output, and only a durable row makes that
            # visible. `decisions.content` is unbounded Text; the payload is capped at source.
            memory.add_decision(
                run_id, "plan_fallback_evidence", str(state["plan_fallback_evidence"])
            )
        _record_contracts(memory, state, run_id, project_id, item_id, commit_sha, workspace_root)
        receipt = receipt_json(state)
        gate = state.get("gate_decision")
        if isinstance(gate, dict):
            memory.add_decision(
                run_id,
                "gate_decision",
                (
                    f"action={gate.get('action', '')}; "
                    f"reasons={','.join(str(r) for r in gate.get('reasons', []))}; "
                    f"verdict={gate.get('reviewer_verdict', '')}; "
                    f"tests_passed={gate.get('tests_passed')}; "
                    # What that tests_passed was WORTH (ADR-0034) — a green `compileall` and a
                    # green pytest suite are not the same evidence, and the record must say so.
                    f"validation_strength={gate.get('validation_strength', 'unknown')}; "
                    f"human_override={bool(gate.get('human_override'))}"
                ),
            )
            # The machine-readable receipt (ADR-0071 amendment): the same verdict plus the
            # priced residual, vouch diagnosis, and mutation tri-state as JSON — the flat
            # string above is a parsing contract (lib/runs.ts) and stays byte-identical.
            if receipt:
                memory.add_decision(run_id, "receipt", receipt)
        for note in state.get("feedback", []):
            memory.add_decision(run_id, "gate", note)
        plan = state.get("validation_plan")
        if isinstance(plan, dict):
            memory.add_decision(run_id, "validation_plan", json.dumps(plan))
        if state.get("tests_passed") is not None:
            # One evidence row per executed step; plan-less (legacy/fake)
            # states keep the single-row fallback.
            results = (plan or {}).get("results") if isinstance(plan, dict) else None
            if results:
                for r in results:
                    status = (
                        "TIMED OUT" if r.get("timed_out") else f"exit code {r.get('exit_code')}"
                    )
                    memory.add_test_result(
                        run_id,
                        bool(r.get("ok")),
                        f"[step {r.get('name')}: {status}]\n{r.get('output', '')}",
                    )
            elif state.get("test_output"):
                memory.add_test_result(
                    run_id, bool(state.get("tests_passed")), state["test_output"]
                )
        # tests_passed None → NO TestResult row: there is no evidence to store;
        # the validation_plan decision carries the honest reason instead.
        findings_text = state.get("findings_text")
        if findings_text and findings_text != "No security findings.":
            memory.add_decision(run_id, "scan", findings_text)
        # The critic's judgement (#61): reason + per-claim rows, durable at last — before this,
        # a veto left only the bare `critic_vetoed` token in the gate reasons (the 17 sweep
        # vetoes of 2026-08-03 persisted zero reason text).
        ov = state.get("outcome_verdict")
        if isinstance(ov, dict):
            memory.add_decision(run_id, "critic", json.dumps(ov))
        if state.get("diff"):
            memory.add_repo_change(run_id, state["diff"], commit_sha)
            # Embedding intentionally omitted — nothing reads it. See `_embed`.
            memory.add_artifact(run_id, "diff", state["diff"])
        report = state.get("report_path")
        if report:
            memory.add_artifact(run_id, "report", str(report))
        # Claim ledger (ADR-0079 Wave 2): the run's claims + their evaluated verdicts, joined
        # into one row per claim. Written BEFORE record_run like every other evidence row (the
        # ordering invariant): a crashed persist can leave claim rows without a final status,
        # never a final status without its claim evidence.
        claims = state.get("claims") or []
        if claims:
            memory.add_run_claims(run_id, claim_rows(claims, state.get("claim_dispositions")))
        # Finalize the status LAST — only now that every evidence row is durable.
        memory.record_run(
            run_id=run_id,
            source=source,
            branch=branch,
            task=state.get("task", ""),
            status="APPROVED" if state.get("approved") else "NOT APPROVED",
            # Back-compat boolean only; validation_status carries the honest
            # tri-state so "unavailable" is never durably recorded as "failed", and
            # a deliver-with-caveat (P3) is recorded "unverified", not "pass".
            tests_passed=bool(state.get("tests_passed")),
            validation_status=(
                "unverified"
                if state.get("validation_unverified")
                else "unavailable"
                if state.get("tests_passed") is None
                else ("pass" if state.get("tests_passed") else "failed")
            ),
            iterations=int(state.get("iteration", 0)),
            commit_sha=commit_sha,
            # The seal (#63): the version that PRODUCED this run, and — only when a
            # receipt row exists — its deterministic id. No receipt → no receipt id.
            engine_version=mosaera_core.__version__,
            receipt_id=(
                make_receipt_id(run_id, commit_sha, mosaera_core.__version__, receipt)
                if receipt
                else None
            ),
        )
    except Exception as exc:
        print(f"  WARNING     : durable memory write failed ({exc}); run completed regardless.")
