"""The per-turn helpers: what a reply used, what the project remembers, what to redact.

Split out of ``pm_turn.py`` when that file reached the god-file ceiling. Cohesive by subject —
these three ENRICH or SANITISE a turn, where what remains in ``pm_turn`` is the turn's control
flow: run the model, decide whether it worked, record what came back.

Every one of them is best-effort by contract. A project whose history cannot be read, or an
evidence lookup that fails, must cost the operator that detail and never the conversation.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from mosaera_core.evidence import reconcile
from mosaera_core.project_memory import open_work_and_blockers, recurring_failures

from mosaera_api.pm_sections import project_memory_block
from mosaera_api.redact_chat import redact_secrets

_log = logging.getLogger(__name__)

#: Item states whose evidence is still worth reconciling — a finished item is settled.
_EVIDENCE_STATUSES = frozenset({"todo", "in_progress", "deferred", "in_review"})


def _redacted_json(value: Any) -> Any:
    """A proposal with credential-shaped substrings scrubbed from every string it contains.

    `redact_secrets` takes text and a changeset is nested JSON, so the walk lives here rather than
    stringifying the payload — the card needs the structure back in order to re-render.
    """
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, list):
        return [_redacted_json(v) for v in value]
    if isinstance(value, dict):
        return {k: _redacted_json(v) for k, v in value.items()}
    return value


def _project_memory_block(memory: Any, project_id: str) -> str:
    """What this project's own records say, counted — see `mosaera_core.project_memory`.

    THE STANDING CORE ONLY: what is open and blocked, and how this project tends to fail. Those
    two change how Quincy reasons about any question, which is why they ride every turn the way
    the charter, doctrine and map do — a keyword gate would stay silent on "what should we do
    next?", the very turn where history matters most, because that sentence names no topic.

    The detail is deliberately NOT here. Per-item run histories, the text of acceptance criteria
    that failed, and the orphaned-history count are situational: worth a lot when the conversation
    is already on an item, worth nothing on "thanks". They stay in `mosaera-memory` until a
    read-only history TOOL lands, so Quincy can pull them when the conversation actually goes
    there rather than paying for them on every turn. Core is ~170 tokens against ~405 for the
    full set; prompt caching covers the difference on Anthropic but is off for ollama, which is
    the default deployment.

    Best-effort by design. This is context, not a control: a project whose history cannot be read
    (a store one migration behind, a reader not present on an older MemoryStore) must still get a
    chat turn, so every failure here degrades to no block rather than a 500. The alternative —
    letting a background question break the foreground conversation — trades a real capability for
    a cosmetic one.
    """
    reader = getattr(memory, "history_runs", None)
    if reader is None:  # a store without the history mixin
        return ""
    try:
        runs = memory.history_runs(project_id)
        items = memory.history_items(project_id)
        return project_memory_block([open_work_and_blockers(items), recurring_failures(runs)])
    except Exception:
        _log.warning("project memory unavailable for %s", project_id, exc_info=True)
        return ""


def _attach_evidence(memory: Any, detail: dict[str, Any]) -> None:
    """Fold the claim ledger into each live backlog row as `evidence`, in place.

    Deliberately narrow: only items whose bar is still open, only a read, and every failure
    swallowed per item. The ledger is an enrichment — an operator asking about their backlog must
    not lose the turn because one row is malformed.
    """
    reader = getattr(memory, "list_item_claims", None)
    if reader is None:
        return
    for item in detail.get("backlog") or []:
        if str(item.get("status") or "") not in _EVIDENCE_STATUSES:
            continue
        if not str(item.get("acceptance") or "").strip():
            continue
        with contextlib.suppress(Exception):
            found = reconcile(str(item["acceptance"]), reader(int(item["id"])), int(item["id"]))
            item["evidence"] = {
                "criteria": [
                    {"text": c.text, "verdict": c.verdict, "oracle_ref": c.oracle_ref}
                    for c in found.criteria
                ],
                "measured": found.measured,
                "fully_evidenced": found.fully_evidenced,
            }


#: The three causes a turn can fail for. Public so the coverage guard can read them without
#: hand-listing a second copy — a vocabulary with two origins is one that drifts.
