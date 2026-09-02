"""Run one QMB case: hand the PM a fixture, record what it proposed. No scoring here.

Separated from scoring so a run can be recorded once and re-scored later without paying for the
model again — and so the scorer can be tested against canned observations, which is what lets the
suite prove its own cases are failable.

`core` may not import `agents` or `api`, so the two steps that belong to the app arrive as
callables: asking the PM to propose, and validating a changeset. That is the same inversion
`intake_ask.run_intake_pass` uses, for the reason it gives — "a harness wants the exception".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mosaera_core.pmbench.cases import QMBCase


@dataclass(frozen=True)
class PMResponse:
    """What one PM entry point returned. `ops` is the structured proposal, `reply` the prose."""

    reply: str = ""
    ops: tuple[dict[str, Any], ...] = ()


#: Ask the PM, through a real entry point, given (case, path). Returns what it said.
ProposeFn = Callable[[QMBCase, str], PMResponse]
#: Validate a proposed changeset against the fixture rows. Returns the refusal, or "" if accepted.
#: The app owns this because the real validator lives there; the harness only records the verdict.
ValidateFn = Callable[[QMBCase, tuple[dict[str, Any], ...]], str]


@dataclass(frozen=True)
class CaseObservation:
    """Everything one case run produced. Pure data — serialisable, re-scorable, no model."""

    case_id: str
    case_class: str
    chat: PMResponse | None = None
    curate: PMResponse | None = None
    #: The validator's refusal for each path, "" when it accepted. Missing key = path not driven.
    refusals: dict[str, str] = field(default_factory=dict)
    #: Set when the model call itself failed. A failed call is NOT a zero: it is an absent
    #: measurement, and averaging it in as zero would understate the model rather than measure it.
    error: str = ""

    @property
    def usable(self) -> bool:
        return not self.error


def run_pm_case(case: QMBCase, propose: ProposeFn, validate: ValidateFn) -> CaseObservation:
    """Drive the entry points this case declares and record the result.

    Deliberately NOT best-effort about the case's own declaration: if a case says `paths = "both"`
    it gets both, because the consistency dimension is only meaningful when the same fixture and
    the same request went down two paths in one run. Comparing a chat from one run against a curate
    from another would measure drift between runs, not disagreement between paths.
    """
    chat = curate = None
    refusals: dict[str, str] = {}
    try:
        if case.drives_chat:
            chat = propose(case, "chat")
            # A blank CHAT reply is the model returning nothing usable — the product has the same
            # concept and its own fallback sentence for it. That is an ABSENT measurement, not a
            # wrong answer, and scoring it zero would report the model as worse than it is.
            #
            # Only the chat path. `curate` returns ops and no prose by construction, and zero ops
            # there is a real answer — it is precisely what the no-op control must produce.
            if not chat.reply.strip():
                return CaseObservation(
                    case_id=case.id,
                    case_class=case.case_class,
                    chat=chat,
                    error="empty reply: the model returned nothing usable",
                )
            refusals["chat"] = validate(case, chat.ops)
        if case.drives_curate:
            curate = propose(case, "curate")
            refusals["curate"] = validate(case, curate.ops)
    except Exception as exc:
        return CaseObservation(
            case_id=case.id,
            case_class=case.case_class,
            chat=chat,
            curate=curate,
            refusals=refusals,
            error=f"{type(exc).__name__}: {exc}",
        )
    return CaseObservation(
        case_id=case.id,
        case_class=case.case_class,
        chat=chat,
        curate=curate,
        refusals=refusals,
    )


def render_backlog_rows(case: QMBCase) -> list[dict[str, Any]]:
    """The fixture's rows in the shape the real store returns, for the caller's context builder."""
    return [dict(i) for i in case.items]
