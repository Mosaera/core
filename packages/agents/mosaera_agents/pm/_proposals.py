"""The three fenced PROPOSALS a PM reply can carry, and how each is parsed.

Split out of ``_backlog.py`` when that file reached the modularity ceiling, on the same reasoning
as ``_chat_prompt.py``: cohesive by subject. A chat turn can carry a backlog CHANGESET, a project
CHARTER, and an intake CLARIFICATION, and all three obey one discipline — a distinct fence, a lazy
single-run match, ``None``/empty on anything malformed, and fields clamped before they leave. Read
as a whole, that discipline is visible; scattered through a 500-line module it is three
coincidences.

Every function here is READ-ONLY over model output and mints nothing. ADR-0080: the model may
propose, and the operator's acceptance is what makes a proposal binding — so the job of this
module is to decide what was proposed, never whether it is true.

``_JSON_BLOCK`` lives here and is imported BACK by ``_backlog.py`` for ``_extract_json_array``
(the decompose/curate path), one direction only and one copy — the same arrangement
``_chat_prompt.py`` uses for ``_CHANGESET_OPS``, and for the same reason: two copies of the fence
pattern is exactly how the parser and the stripper drifted apart before.
"""

from __future__ import annotations

import json
import re
from typing import Any

# The changeset fence. ONE pattern, used by `_extract_changeset` below and imported back by
# `_backlog.py`'s `_extract_json_array` — two copies of it (an inline one in the extractor and a
# second beside the stripper) is what let the parser and the stripper drift apart in the first
# place.
#
# The tag is optional but the FENCE is not, on the chat path. Do NOT "harmonise" this with
# `_CHARTER_BLOCK`'s `[^{]*?` trailing-words tolerance: `[^\[]*?` here would let a ```charter or
# ```clarify block match too, the moment its body contained a bracket, collapsing three
# deliberately distinct conventions into one.
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)


def _extract_changeset(text: str) -> tuple[list[dict[str, Any]], str]:
    """The proposed backlog ops, and the reply with exactly that block removed.

    CHAT ONLY, and the fence is mandatory here — the same discipline the ```charter and
    ```clarify proposals either side of it already keep. `_extract_json_array` would also accept
    an UNFENCED array (first `[` to last `]` of the whole reply), but the chat prompt has never
    asked for that form ("END your reply with a fenced ```json array"), and the only thing
    standing between ordinary prose and a spurious backlog proposal was the SHAPE of the data:
    dicts carrying an `op` key. Shape is not intent. Quoted fixtures, migration manifests and
    this project's own changeset examples are all op-shaped, and a PM who could read files would
    meet them (slice 1 of docs/design/agentic-pm-chat.md; ADR-0111 §4).

    Returning the ops AND the text together is the point. The bug this replaces was a parser and
    a stripper that disagreed about which form had been parsed; fusing them makes "strip exactly
    what was extracted" a property of the function's shape rather than a comment two people have
    to keep true. Removal is by span, not by `str.replace`, so an identical earlier block is
    never the one that disappears.

    A refused array is therefore left ALONE in the visible reply: the operator sees raw JSON and
    no approval card, which is the honest rendering of "he tried to propose and it did not
    take". Stripping it would hide the refusal — the one outcome worse than either.

    The LAST fenced array wins, not the first: the prompt says to END the reply with it, so an
    earlier block is an illustration, and `_last_ai_text` on the planning path already settles
    "which of several utterances is the answer" the same way. Only the winning block is removed;
    an illustration stays visible as what it is.
    """
    for match in reversed(list(_JSON_BLOCK.finditer(text))):
        try:
            parsed = json.loads(match.group(1))
        except (ValueError, TypeError):
            # A fenced block we could not read is not a proposal, and it does not get removed
            # either — a proposal that silently vanishes is worse than one visibly refused.
            continue
        if not isinstance(parsed, list):
            continue
        ops = [op for op in parsed if isinstance(op, dict) and str(op.get("op", "")).strip()]
        # Stripped on a successful LIST parse, not on yielding ops: a genuine `[]` is a
        # well-formed empty proposal, and leaking its raw JSON would punish correct output.
        return ops, text[: match.start()] + text[match.end() :]
    return [], text


# The charter PROPOSAL block (#42): a fenced ```charter object, distinct from the ```json
# changeset ARRAY so the two conventions can never collide. Parsed to a plain dict; the
# TRUSTED charter row is only ever written by the operator's admin-gated PUT — the model
# proposes, a human confirms (ADR-0047 §1).
# The fence tag tolerates trailing words on the fence line ("```charter JSON object" —
# a live weak-model habit); a single LAZY run of non-brace chars reaches the first "{", so a
# plain ```json block still can't match (no literal "```charter" prefix). One quantifier to
# the brace — the old `[^\n{]*\s*` pair overlapped on whitespace and backtracked quadratically
# on a long brace-less whitespace run (MR3 red-team FIX-NOW; the model-output path is
# human-blocking in pm_chat, so a jailbroken model could stall a worker).
_CHARTER_BLOCK = re.compile(r"```charter[^{]*?(\{.*?\})\s*```", re.DOTALL)

# The intake-clarification PROPOSAL block (ADR-0080 §1, Wave 3): a fenced ```clarify object,
# same discipline as ```charter (distinct tag, lazy single-run to the brace, deny-by-default
# parse, clamped fields). Emitted for an item the SERVER marked askable — UNDER_SPECIFIED or
# UNDECIDABLE since 2026-08-04; the request is stored on
# the item and the operator resolves it — an accepted proposal becomes the item's acceptance
# via the validated `enhance` path, i.e. ENTAILED by operator acceptance, never by the model.
_CLARIFY_BLOCK = re.compile(r"```clarify[^{]*?(\{.*?\})\s*```", re.DOTALL)


def _extract_clarify(text: str) -> dict[str, Any] | None:
    """Parse a ```clarify fence into {item_id, claim_text, why, proposals} — or None.

    Deny-by-default: malformed JSON, a non-dict, a non-int item_id, or no usable proposals
    all yield None (the reply simply carries no clarification). Fields clamped to 2000 chars,
    max 3 proposals — the store re-validates at its own boundary."""
    m = _CLARIFY_BLOCK.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    raw_id = data.get("item_id")
    if raw_id is None:
        return None
    try:
        item_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    proposals = [
        str(x).strip()[:2000]
        for x in (data.get("proposals") or [])
        if isinstance(x, str) and x.strip()
    ][:3]
    claim_text = str(data.get("claim_text") or "").strip()[:2000]
    if not proposals or not claim_text:
        return None
    return {
        "item_id": item_id,
        "claim_text": claim_text,
        "why": str(data.get("why") or "").strip()[:2000],
        "proposals": proposals,
    }


# Kept in sync with mosaera_memory.models_charter.CHARTER_POSTURES (agents never imports the
# persistence layer); the sync is enforced by test_charter_postures_in_sync in apps/api.
_POSTURES = frozenset({"free", "business", "regulated"})


def _extract_charter(raw: str) -> dict[str, str] | None:
    """The proposed charter from a ```charter block, or None. Deny-by-default: malformed
    JSON, a non-dict, or an out-of-set posture yields None (no partial proposals)."""
    m = _CHARTER_BLOCK.search(raw)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(1))
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    posture = str(parsed.get("posture", "")).strip().lower()
    if posture not in _POSTURES:
        return None
    return {
        "goal": str(parsed.get("goal", "")).strip()[:2000],
        "constraints": str(parsed.get("constraints", "")).strip()[:2000],
        "posture": posture,
    }
