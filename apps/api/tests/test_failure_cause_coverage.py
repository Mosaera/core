"""Every failure cause the server can emit has words for the operator.

The chat reuses the planner's closed vocabulary — `budget_exhausted | model_failed | empty` — and
the web renders each one from `apps/web/src/lib/plain.ts`. Nothing but a test connects the two:
Python emits the token, TypeScript owns the sentence, and a cause added on one side is silent on
the other until somebody notices.

Written in Python, and reading the TS file as text, for the reason the gate-reason coverage guard
gives: the producing side is where the vocabulary lives, so the guard belongs where a new token
gets added — not one language over, where it would be discovered later or not at all.

This is what keeps slice 3's `budget_exhausted` from reaching an operator as raw jargon: the
token, its copy and this check all exist before the loop that can produce it.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PLAIN = _ROOT / "apps" / "web" / "src" / "lib" / "plain.ts"


def _copy_deck_keys() -> set[str]:
    block = re.search(
        r"const PM_TURN_FAILURE: Record<string, string> = \{(.*?)\n\};", _PLAIN.read_text(), re.S
    )
    assert block, "PM_TURN_FAILURE is gone from the copy deck — the operator has no words"
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.M))


def _server_causes() -> set[str]:
    from mosaera_api.pm_turn import FAILURE_CAUSES

    return set(FAILURE_CAUSES)


def test_every_server_cause_has_an_operator_sentence() -> None:
    missing = _server_causes() - _copy_deck_keys()
    assert not missing, f"no operator copy for {sorted(missing)} — they would render as raw jargon"


def test_the_copy_deck_invents_no_cause_the_server_cannot_emit() -> None:
    """The other direction: dead copy is a sentence nobody will ever read, and it makes the
    vocabulary look larger than it is."""
    extra = _copy_deck_keys() - _server_causes()
    assert not extra, f"copy for causes the server never emits: {sorted(extra)}"


def test_the_vocabulary_is_the_planner_s_and_has_not_drifted() -> None:
    """One vocabulary, two surfaces. `fallback_reason` is the origin — the chat reuses its three
    tokens rather than minting synonyms, so the run pages and the conversation name the same
    things the same way. If either side changes, this fails instead of letting them drift."""
    from mosaera_agents.pm._planning import _BUDGET_SENTINEL, _TRANSPORT_SENTINEL, fallback_reason

    def _ai(text: str) -> object:
        return type("M", (), {"type": "ai", "content": text})()

    produced = {
        fallback_reason({"messages": []}),
        fallback_reason({"messages": [_ai(f"{_BUDGET_SENTINEL}: run limit (12/12)")]}),
        fallback_reason({"messages": [_ai(f"{_TRANSPORT_SENTINEL} 3 attempts")]}),
    }
    assert produced == _server_causes()
