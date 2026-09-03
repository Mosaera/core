"""One place that re-surveys the machine for the choice handler.

Its own function because the handler must survey with the SAME arguments the screen did — a second
survey with different settings would number the rows differently and install the wrong tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mosaera_core.prereqs import Found, missing, survey

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp


def missing_now(app: SetupApp) -> list[Found]:
    return actionable(missing(survey(app.settings.docker_bin, app.platform)))


def actionable(gaps: list[Found]) -> list[Found]:
    """One row per ACTION, not one per fact.

    Docker and its Compose plugin are two separate facts — a distribution can ship one without the
    other, and the survey is right to probe them separately — but on a machine with no Docker at all
    they are closed by the SAME command. The screen offered "Install Docker  curl … | sudo sh" and
    "Install Docker Compose  curl … | sudo sh" one under the other, which asks the operator to
    choose between two spellings of one action and makes a missing Docker look like two problems.

    Stated as a rule rather than as a special case for Docker: two gaps whose plan runs the same
    command are one thing to do. The TABLE still lists both — what shape the machine is in is a
    different question from what to do about it, and the compose row says "needs Docker first"
    rather than pretending to be an independent gap.
    """
    seen: set[tuple[str, ...]] = set()
    out: list[Found] = []
    for gap in gaps:
        # A plan with no runnable steps is identified by the documentation it points at: on macOS
        # both Docker rows say "read the Docker Desktop page", which is also one action.
        key = tuple(step.command for step in gap.plan.steps) or (gap.plan.docs,)
        if key in seen:
            continue
        seen.add(key)
        out.append(gap)
    return out
