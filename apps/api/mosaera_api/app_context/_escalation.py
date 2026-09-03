"""Layer-2 park→ship disposition, resilient-sweep re-curation/defer, and the ESCALATE arm.

The rungs an autonomous item run descends after it ends honestly ``incomplete``. The FIRST rung —
try a stronger model, and check the stronger model actually spoke — lives in
``_model_escalation.py``: it was split out at the 500-line god-file ceiling, and it is cohesive on
its own terms (one question the rest of this file does not ask).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mosaera_core.agents_bridge import build_default_team
from mosaera_core.config import Role, Settings
from mosaera_core.disposition import (
    AuthorTestsFn,
    close_oracle_gap,
    convertible_park_class,
    is_oracle_unverified_park,
    supersede_engine_tests,
    trapping_engine_tests,
)
from mosaera_core.escalate_arm import ask_withheld_reason
from mosaera_core.intake_ask import REACHABILITY
from mosaera_core.models import get_chat_model
from mosaera_core.sandbox import SandboxUnavailable, SandboxWorker, create_sandbox
from mosaera_core.testintegrity import protected_test_paths
from mosaera_core.tools.repo import Workspace, build_repo_tools, open_project_workspace
from mosaera_core.validation import resolve_plan, run_plan

from mosaera_api.app_context._model_escalation import ModelEscalationMixin
from mosaera_api.runner import RunSession
from mosaera_api.schemas import ProjectBusy

# The convertible classes live in core (shared with the bench measurement); the sweep rung reads
# them off ``session.final``. See ``mosaera_core.disposition.convertible_park_class``. The alias
# keeps the original class-1 predicate importable for tests/back-compat.
_is_convertible_park = is_oracle_unverified_park


def _task_text(item: Mapping[str, Any]) -> str:
    title = str(item.get("title") or "")
    desc = str(item.get("description") or "").strip()
    return f"{title}\n\n{desc}" if desc else title


def _held_out_factory(role: Role, settings: Settings) -> Any:
    """A model factory that authors the disposition test with the HELD-OUT critic model instead of
    the tester default (which is the coder model). Class 2 (the engine-blocked give-up) deletes the
    only in-tree oracle that flagged the code, so it needs MORE independence than class 1: a fresh
    test written by the same model family that wrote the wrong code shares its blind spot (red-team
    R1). Only the tester role is rebound; every other role resolves normally."""
    return get_chat_model("critic" if role == "tester" else role, settings)


def _open_author_context(
    settings: Settings, project_id: str, run_id: str, *, held_out: bool = False
) -> tuple[Workspace, SandboxWorker, AuthorTestsFn] | None:
    """Assemble a standalone tester-authoring context over the project's PARKED clone — a tester
    agent + sandbox callable OUTSIDE the run graph (the outside-the-graph mandate). Reopens the
    clone WITHOUT resetting (a park never commits, so the delivered diff is still uncommitted on
    disk) and on whatever branch the run left. The tester is forced ON regardless of the run's
    ``tester_enabled`` — authoring the missing independent test is this rung's whole purpose;
    ``approval_gate=False`` because this is the unwatched autonomous path (same as an autonomous
    run's auto-approve). The tester's writes are confined to ``tests/`` AND every PRE-EXISTING
    ``tests/`` file is ``protected_paths`` — so at the tool layer it can only CREATE NEW tests,
    never edit/weaken a baselined one (the tamper-laundering vector; ``close_oracle_gap`` re-checks
    as defense-in-depth). ``held_out`` authors with the critic (independent) model — required for
    class 2. Returns ``None`` when no sandbox is reachable (can't run the real oracle ⇒ can't verify
    ⇒ the park stands)."""
    workspace = open_project_workspace(settings.projects_dir, project_id, run_id)
    try:
        sandbox = create_sandbox(
            settings.sandbox_backend,
            workspace.root,
            image=settings.sandbox_image,
            docker_bin=settings.docker_bin,
            default_timeout=settings.sandbox_timeout,
            install_network=settings.sandbox_install_network,
            index_url=settings.sandbox_index_url,
            allow_install=settings.sandbox_install,
        )
    except SandboxUnavailable:
        return None
    # Refuse edits/deletes to any test already on disk — the tester only ever AUTHORS new ones.
    protected_tests = protected_test_paths(workspace)
    tool_kwargs: dict[str, Any] = {
        "approval_gate": False,
        "install": settings.sandbox_install,
        "install_timeout": settings.sandbox_install_timeout,
    }
    all_tools = build_repo_tools(workspace, sandbox, **tool_kwargs)
    tester_tools = build_repo_tools(
        workspace, sandbox, write_prefix="tests/", protected_paths=protected_tests, **tool_kwargs
    )
    factory = _held_out_factory if held_out else get_chat_model
    team = build_default_team(settings, all_tools, tester_tools, factory)

    def author(instruction: str) -> None:
        team.author_tests(instruction, None)

    return workspace, sandbox, author


class EscalationMixin(ModelEscalationMixin):
    def _try_close_named_gap(
        self,
        project_id: str,
        item: dict[str, Any],
        mode: str,
        run_id: str,
        session: RunSession,
        used_settings: Settings,
    ) -> bool:
        """Layer-2 park→ship disposition (#76, ADR-0074 + the ADR-0075 widening). An autonomous
        item run parked in one of the two CONVERTIBLE classes: (1) ``oracle_unverified`` — a green
        suite that was the coder's OWN, no independent oracle vouched; (2) the engine-blocked
        give-up — the run gave up because the ONLY failing tests were the ENGINE'S own
        authored/protected oracle (a wrong — sometimes unsatisfiable — test the coder may not
        edit). Outside the run graph, author an independent asserting test for the item's
        acceptance and re-run the REAL sandboxed oracle: green + comprehensive-mutation-proven
        ships VERIFIED in place; anything else stays honestly parked. For class 2 the trapping
        engine tests are SUPERSEDED (deleted — the engine retracts its own work-product; never
        repaired) before verification, and the WHOLE remaining suite must be green before the
        commit. Bounded to one attempt (no loop). Gated ``mode == "autonomous"`` +
        ``disposition_gap_close`` (default OFF).

        **The ship authority is the deterministic execution, never an LLM judgment** — the model
        only AUTHORS the test (the ADR-0070 dead-end's named successor). The whole author→verify→
        commit runs while HOLDING the project mutex (the parked diff is uncommitted + otherwise
        unlocked; a concurrent run's start-reset would wipe it), released before the sweep advances.
        Returns True when the diff was verified + shipped (so ``_after`` skips the pause note),
        else False to fall through to the recurate/defer rung with the honest park preserved."""
        if self.history is None or mode != "autonomous":
            return False
        if not used_settings.disposition_gap_close:
            return False
        cls = convertible_park_class(session.final or {})
        if cls is None:
            return False  # not a convertible class → leave to recurate/defer unchanged
        # Class 2 (engine-blocked give-up) DELETES the only in-tree oracle that flagged the code and
        # converts a population selected for code-vs-oracle disagreement (red-team R1) — so it may
        # ONLY run with a HELD-OUT tester (the fresh test authored by a different model from the
        # coder). No held-out model available ⇒ no independence ⇒ park stands (deny-by-default).
        held_out = cls == "engine_blocked_give_up"
        if held_out and not used_settings.held_out_ok():
            self._safe_audit(
                run_id, "disposition.no-held-out-tester", "give-up needs an independent tester"
            )
            return False
        # Re-acquire the project mutex for the ENTIRE in-place ship: `_after` released it before
        # this rung, so without re-reserving another run could reserve + reset the clone (git reset
        # --hard + clean -fd) mid-disposition and we'd author/commit against a wiped/foreign tree.
        try:
            self.reserve_project(project_id)
        except ProjectBusy:
            return False  # another run owns the clone → park stands; its on_done drives the sweep
        shipped_note = ""
        try:
            try:
                ctx = _open_author_context(used_settings, project_id, run_id, held_out=held_out)
            except Exception as exc:  # setup must never break the sweep — park stands
                self._safe_audit(run_id, "disposition.setup-failed", f"{type(exc).__name__}: {exc}")
                return False
            if ctx is None:
                self._safe_audit(run_id, "disposition.unavailable", "no sandbox to run the oracle")
                return False
            workspace, sandbox, author_tests = ctx
            superseded: list[str] = []
            if cls == "engine_blocked_give_up":
                # Supersede the trapping engine oracle BEFORE authoring: the engine retracts its
                # own wrong AUTHORED test files (never a baselined/coder file — trapping is a subset
                # of authored_tests by construction), so the fresh independent test replaces them as
                # the shipped oracle; close_oracle_gap's tamper hash never sees them.
                try:
                    trapping = trapping_engine_tests(session.final or {})
                    superseded = supersede_engine_tests(workspace, trapping) if trapping else []
                except Exception as exc:
                    self._safe_audit(
                        run_id, "disposition.supersede-failed", f"{type(exc).__name__}: {exc}"
                    )
                    return False
                if not superseded:
                    # Nothing on disk matched the trapping set — the tree doesn't look like the
                    # park's final state (raced/reset?). Deny-by-default: the park stands.
                    self._safe_audit(run_id, "disposition.no-trapping-on-disk", str(trapping))
                    return False
            try:
                result = close_oracle_gap(
                    workspace,
                    sandbox,
                    author_tests,
                    acceptance=str(item.get("acceptance") or ""),
                    task=_task_text(item),
                    # ALWAYS comprehensive — a survivor in ANY changed region must fail the ship.
                    # #76's soundness rests on this; first-mutation-catches is not enough here.
                    comprehensive=True,
                )
            except Exception as exc:  # a gap-closer fault is inconclusive — never halt the sweep
                self._safe_audit(run_id, "disposition.faulted", f"{type(exc).__name__}: {exc}")
                return False
            if result.verdict != "verified":
                # unverified = a real check said no (code wrong / not a real oracle); unavailable =
                # couldn't produce a check. Either way the honest park is preserved (deny-default).
                self._safe_audit(
                    run_id, "disposition.not-verified", f"{cls}: {result.verdict}: {result.reason}"
                )
                return False
            if superseded:
                # The give-up class deleted engine test files — the WHOLE remaining suite must be
                # green before shipping (a deleted file another test imported would break the
                # delivered tree; the authored-suite green step alone can't see that).
                try:
                    suite = run_plan(resolve_plan(workspace, None, install=False), sandbox)
                except Exception as exc:
                    self._safe_audit(
                        run_id, "disposition.suite-check-faulted", f"{type(exc).__name__}: {exc}"
                    )
                    return False
                if suite.passed is not True:
                    self._safe_audit(
                        run_id, "disposition.suite-not-green", "post-supersession suite failed"
                    )
                    return False
            # VERIFIED → commit the delivered diff + the authored test IN PLACE (reproduces
            # deliver_node's commit) so the conversion is indistinguishable from a clean delivery.
            supersession_note = (
                f"\nSuperseded engine tests: {', '.join(superseded)}." if superseded else ""
            )
            try:
                commit = workspace.commit_all(
                    f"mosaera: {_task_text(item)}\n\nRun: {run_id}\n"
                    f"Layer-2 verified ({cls}, #76): the independent test "
                    f"{', '.join(result.authored)} passes the delivered code and catches "
                    f"mutations of the change.{supersession_note}"
                )
            except Exception as exc:  # a commit fault must not leave a half-shipped item
                self._safe_audit(
                    run_id, "disposition.commit-failed", f"{type(exc).__name__}: {exc}"
                )
                return False
            if not commit:
                return False  # nothing staged (empty diff) → not a real ship, fall through
            # Mark delivered INSIDE the lock, guarded: a committed-but-unmarked item would be
            # re-selected by advance_project and delivered twice. On a mark fault, do NOT advance —
            # leave the committed item for the recurate/defer fallthrough (a human reconciles).
            try:
                self.history.update_backlog_item(item["id"], status="in_review")
            except Exception as exc:
                self._safe_audit(
                    run_id, "disposition.mark-failed", f"{commit[:10]}: {type(exc).__name__}"
                )
                return False
            shipped_note = f"{cls}: {commit[:10]}: {', '.join(result.authored)}" + (
                f" (superseded: {', '.join(superseded)})" if superseded else ""
            )
            self._safe_audit(run_id, "disposition.verified-ship", shipped_note)
        finally:
            self.release_project(project_id)
        if not shipped_note:
            return False  # defensive: only the full verified+committed+marked path sets it
        # Lock released → the sweep may advance (advance_project re-reserves via launch_item). MR
        # open + advance are best-effort last-mile (they never un-ship the committed item).
        self.history.update_project(project_id, error="")
        self._maybe_open_item_mr(project_id, item["id"], run_id)
        self.advance_project(project_id)
        return True

    def _try_recurate_or_defer(
        self, project_id: str, item: dict[str, Any], mode: str, run_id: str, session: RunSession
    ) -> bool:
        """Resilient autonomous sweep (ADR-0023). An autonomous item run ended honestly
        ``incomplete`` and model escalation couldn't save it — instead of halting the whole
        project, DEFER this item (surfaced with its reason) and keep delivering the rest.
        Opt-in ``resilient_recuration`` first asks Quincy to re-curate the stuck item
        (split / re-scope / set-deps) so it might be retried in a better shape. Always ends by
        advancing the sweep. Returns True when handled (so ``_after`` skips the pause note).
        Loop-safe: a ``deferred`` item drops out of the picker permanently (until a human/Quincy
        revives it), and re-curation is one-shot per stuck event."""
        if self.history is None or mode != "autonomous":
            return False
        settings = Settings.from_env()
        if not settings.resilient_sweep:
            return False  # knob OFF → fall through to today's pause-and-halt behavior
        item_id = item["id"]
        reason = getattr(session, "termination_reason", None) or "stuck"

        # Opt-in: let Quincy re-curate the stuck item before we defer it. Deterministic applier
        # (deny-by-default); autonomous-only auto-apply mirrors the ADR-0012/0022 mode split.
        if settings.resilient_recuration:
            # Lazy import: projects.py imports this module (context) — importing it at module
            # scope would cycle. The sweep calling Quincy is a new capability (ADR-0023).
            from mosaera_api.projects import apply_backlog_changeset, curate_backlog

            try:
                title = str(item.get("title") or f"item {item_id}")
                instruction = (
                    f"The backlog item '{title}' got stuck ({reason}). Re-scope, split, or "
                    "set dependencies so it (or smaller pieces of it) can be delivered, and so "
                    "the rest of the backlog can proceed. Propose only what genuinely helps."
                )
                changeset = curate_backlog(self.history, project_id, instruction=instruction)
                if changeset:
                    apply_backlog_changeset(self.history, project_id, changeset)
                    self._safe_audit(run_id, "sweep.recurated", f"{len(changeset)} op(s): {reason}")
            except ValueError:
                # A malformed / no-mix-violating changeset is rejected wholesale — fall through
                # to a plain defer rather than breaking the sweep.
                pass
            except Exception as exc:  # never let re-curation break the sweep
                self._safe_audit(run_id, "sweep.recurate-failed", str(exc))

        # Precedence: DEFER the stuck item so the picker skips it and the sweep continues —
        # UNLESS re-curation removed it (split/delete), in which case its id is gone and any
        # fresh children are new todos the sweep will try. We never retry the SAME id in-place:
        # that keeps the ladder provably loop-safe (each stuck event terminally defers-or-removes
        # its item; a bounded retry-in-place is future work with an attempt counter).
        if self.history.get_backlog_item(item_id) is None:
            self._safe_audit(run_id, "sweep.recurated-removed", reason)
        else:
            self.history.update_backlog_item(item_id, status="deferred")
            self._safe_audit(run_id, "sweep.deferred", reason)

        self.history.update_project(project_id, error="")
        self.advance_project(project_id)
        return True

    def _try_escalate_arm(
        self,
        item: dict[str, Any],
        run_id: str,
        session: RunSession,
        used_settings: Settings,
    ) -> bool:
        """The ESCALATE arm (#64 F49) — the close-the-gap arm's opposite: STOP and ASK.

        That arm retracts the engine's own wrong tests and ships. This one fires when the producer
        raised its hand and EVERY failing test is one it may not edit — so the acceptance bar itself
        is the blocker, and no amount of re-planning or re-running can move it. The only party who
        can is the operator, because only the operator owns requirements.

        Measured on the guided corpus (`#64`): the producer diagnosed the broken test correctly in
        6 of 6 runs, was re-scoped back at the same wall each time, and the run was recorded as
        though the agent had flailed. The objection was right and nothing received it.

        It NEVER ships and NEVER edits a test. It raises a clarification on the ITEM
        (``set_item_clarification``, ADR-0080) with the blocking test named and DIRECTIONS for the
        operator — never acceptance text, which the store enforces (ADR-0091).

        Returns True when an ask was recorded, so the caller skips the recurate/defer rung: a
        deferred item drops out of the picker, which would bury the very question we just raised.

        It also returns True when a prior affirmation SUPPRESSES the ask. An operator who answered
        "the bar stands, the code is wrong" and then gets the identical question next sweep is being
        nagged toward the one answer that makes it stop — lowering the bar. Asking once is a
        question; asking every sweep is pressure.
        """
        if self.history is None or not used_settings.escalate_arm:
            return False
        final = session.final or {}
        # #68 (ADR-0090 MR3): read what `supervise_node` DECIDED, never re-derive it. The predicate
        # used to run here a second time against a `gate_decision` that had moved on since the stop,
        # so the halves could disagree in both directions — a stale objection blocking a legitimate
        # stop, and a stale clean permitting a stop that then could not ask. Non-empty here means
        # the arm concluded, which is the only condition this ask ever wanted.
        blocking = [str(t) for t in (final.get("ask_blocking_tests") or [])]
        if not blocking:
            return False
        # The exclusions that only the FINAL state can answer — the gate runs after supervise on
        # the give-up path, so a security objection or a veto recorded there is invisible to it.
        withheld = ask_withheld_reason(final)
        if withheld:
            # Recorded AND visible — see `record_withheld_ask` (`Unsuppressible Ask`, ADR-0107).
            self.record_withheld_ask(run_id, item, withheld)
            return False
        named = ", ".join(blocking[:3])
        if self._already_affirmed(item, named):
            self._safe_audit(run_id, "escalate-arm.affirmed", f"bar affirmed for {named}")
            return True
        # The producer's OWN words first. `give_up_reason` is the engine's wrapper around them and
        # is clamped to 80 chars in the durable column, so preferring it loses the detail that makes
        # the ask actionable — the specific contradiction the producer identified.
        reason = str(
            final.get("escalate_reason")
            or final.get("blocked_reason")
            or final.get("give_up_reason")
            or ""
        ).strip()
        try:
            self.history.set_item_clarification(
                int(item["id"]),
                claim_text=f"This item's acceptance cannot be met as written ({named}).",
                why_unbindable=(
                    # Declare the cut: a hard slice can drop a trailing hedge and leave an
                    # assertive fragment where the operator decides whether to move a bar.
                    f"The delivery agent reported: {reason[:600]}"
                    f"{'…' if len(reason) > 600 else ''}\n\n"
                    f"Every failing test ({named}) is protected — the agent is forbidden to edit "
                    "it, so re-running cannot change the outcome. Either the acceptance bar has "
                    "to move, or the item has to supply what the test expects — or the bar is "
                    "right and the code is simply wrong, which is also an answer."
                ),
                # DIRECTIONS, not acceptance text (ADR-0091). This arm is deterministic and has no
                # model: it knows the blocking paths and the producer's words, never what the bar
                # SHOULD become. Emitting these as one-click acceptance made the bar the sentence
                # "Amend the acceptance criteria so tests/x.py can pass as written." Authoring
                # candidates with a model would be worse, not better — an accepted proposal mints
                # ENTAILED, so a model proposal plus one click launders INFERRED into ENTAILED,
                # which claims.py forbids and this arm's own charter contradicts ("only the
                # operator owns requirements").
                proposals=[
                    f"Amend the acceptance criteria so {named} can pass as written.",
                    f"Drop or rewrite the requirement {named} is checking.",
                    "Add the missing input to the item so the test's expectation "
                    "becomes reachable.",
                ],
                axis=REACHABILITY,
                proposal_kind="direction",
            )
        except Exception as exc:  # a failed ask must never break the sweep — the park stands
            self._safe_audit(run_id, "escalate-arm.ask-failed", f"{type(exc).__name__}: {exc}")
            return False
        self._safe_audit(run_id, "escalate-arm.asked", f"blocked by {named}")
        return True

    def _already_affirmed(self, item: dict[str, Any], named: str) -> bool:
        """Did the operator already say this exact bar STANDS (ADR-0091)?

        Matched on the retained record's `claim_text`, which carries the blocking test names — so
        a DIFFERENT wall raises a fresh question and only a repeat of the same one is suppressed.
        Best-effort: a store fault falls through to asking, because a lost suppression costs one
        redundant question while a lost ask costs the operator the question entirely.
        """
        try:
            row = self.history.get_backlog_item(int(item["id"])) or {}  # type: ignore[union-attr]
            record = row.get("clarification_record") or {}
            return bool(
                record.get("status") == "affirmed" and named in record.get("claim_text", "")
            )
        except Exception:
            return False
