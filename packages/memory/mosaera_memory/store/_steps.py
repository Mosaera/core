"""Reading and writing the lookups a PM turn made.

Read-only over the conversation: these rows record reads that already happened, and nothing
consults them to decide anything. The batched loader exists for the same reason its two siblings
do — a transcript of forty turns must not become forty queries.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mosaera_memory.models_steps import STEP_KINDS, MessageStep
from mosaera_memory.store._base import StoreBase


class StepsMixin(StoreBase):
    def add_message_steps(self, message_id: int, steps: list[dict[str, Any]]) -> None:
        """Record what this turn looked up, in the order it looked.

        Unknown kinds are DROPPED rather than stored. The UI renders a step as a sentence from a
        closed vocabulary, so a kind it cannot phrase would appear as a blank line in the record
        of what the PM did — worse than the row's absence. Same posture as `PROPOSAL_KINDS`.
        """
        rows = [s for s in steps if str(s.get("kind", "")) in STEP_KINDS]
        if not rows:
            return
        with self.session() as s, s.begin():
            for seq, step in enumerate(rows):
                s.add(
                    MessageStep(
                        message_id=message_id,
                        seq=seq,
                        kind=str(step["kind"]),
                        tool=str(step.get("tool", ""))[:64],
                        arg=str(step.get("arg", ""))[:64],
                        duration_ms=int(step.get("duration_ms", 0)),
                    )
                )

    def _steps_by_message(self, session: Any, message_ids: list[int]) -> dict[int, list[Any]]:
        """Every turn's steps in one query, ordered — see the `seq` note on the model."""
        out: dict[int, list[Any]] = {}
        if not message_ids:
            return out
        rows = session.execute(
            select(MessageStep)
            .where(MessageStep.message_id.in_(message_ids))
            .order_by(MessageStep.message_id, MessageStep.seq)
        ).scalars()
        for row in rows:
            out.setdefault(row.message_id, []).append(
                {"kind": row.kind, "tool": row.tool, "arg": row.arg, "duration_ms": row.duration_ms}
            )
        return out
