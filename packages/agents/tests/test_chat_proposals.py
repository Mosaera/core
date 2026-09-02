"""The fenced proposals a PM chat reply can carry — and what is refused.

Kept out of ``test_agents_offline.py``: that module sits at the test ratchet's ceiling, and the
guard's rule is to split rather than grow (``scripts/check_file_sizes.py``). New coverage belongs
beside the behaviour it pins.

What these pin, in one sentence: a changeset is a proposal only when the model FENCED it, and an
array that is refused stays VISIBLE. The prompt has always asked for a fence
("END your reply with a fenced ```json array"); the extractor merely used to accept less, with the
SHAPE of the data — dicts carrying an `op` key — as the only guard between ordinary prose and a
backlog proposal. Slice 1 of ``docs/design/agentic-pm-chat.md``; ADR-0111 §4.
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage


def test_an_unfenced_changeset_is_refused_and_stays_visible() -> None:
    """Supersedes the 2026-08-19 fix, which made the strip regex match the unfenced form so a
    parsed changeset stopped ALSO rendering as raw JSON in the operator's chat. That fix answered
    the wrong half: the guard on an unfenced array was the SHAPE of the data (dicts with an `op`
    key), never the author's intent, and the chat prompt has always asked for a fence. So the
    array is no longer a proposal — and precisely because it is not, it is no longer stripped.
    The operator sees the JSON and no approval card: a refusal you can see beats one you cannot.
    """
    from mosaera_agents import pm

    raw = 'Here you go.\n[{"op": "add", "title": "X", "why": "w"}]\nLet me know.'
    reply, changeset, charter, clarify = pm.chat(
        FakeMessagesListChatModel(responses=[AIMessage(content=raw)]), "ctx", [], "add an item"
    )
    assert changeset == []  # not a proposal: the model never fenced it
    assert '"op"' in reply and "[{" in reply  # and not hidden — the attempt is visible
    assert "Here you go." in reply and "Let me know." in reply  # prose survives
    assert charter is None and clarify is None

    # The fenced form keeps working exactly as before.
    fenced = 'Sure.\n```json\n[{"op": "add", "title": "Y", "why": "w"}]\n```'
    reply2, changeset2, _c2, _cl2 = pm.chat(
        FakeMessagesListChatModel(responses=[AIMessage(content=fenced)]), "ctx", [], "add"
    )
    assert len(changeset2) == 1 and "```" not in reply2


def test_prose_containing_brackets_is_never_a_changeset() -> None:
    """The failure mode the fence requirement exists for. The old extractor took the first `[`
    to the last `]` of the WHOLE reply, so any bracketed prose was a parse candidate — only the
    op-key filter stood behind it."""
    from mosaera_agents import pm

    for raw in (
        "The three options are [1, 2, 3] and I'd take the second.",
        'A changeset looks like [{"op": "add", "title": "..."}] — shall I prepare one?',
        "See items [4] and [7]; both depend on the schema work.",
    ):
        _reply, changeset, _c, _cl = pm.chat(
            FakeMessagesListChatModel(responses=[AIMessage(content=raw)]), "ctx", [], "?"
        )
        assert changeset == [], f"prose became a proposal: {raw!r}"


def test_a_bare_fence_without_the_json_tag_still_counts() -> None:
    """The guard is the FENCE, not the language tag: a weak model that opens ``` and forgets to
    write `json` has still marked its intent, and losing its proposal would punish the wrong
    thing."""
    from mosaera_agents import pm

    raw = 'Proposing one item.\n```\n[{"op": "add", "title": "Z", "why": "w"}]\n```'
    reply, changeset, _c, _cl = pm.chat(
        FakeMessagesListChatModel(responses=[AIMessage(content=raw)]), "ctx", [], "add"
    )
    assert [op["op"] for op in changeset] == ["add"]
    assert "```" not in reply and "Proposing one item." in reply


def test_the_last_fenced_changeset_wins() -> None:
    """The prompt says to END the reply with the array, so an earlier block is an illustration.
    `re.search` would have taken the first — a rule the contract never stated. Matches how
    `_last_ai_text` settles the same question on the planning path.

    The illustration is left visible, because only the block that was actually parsed is removed.
    """
    from mosaera_agents import pm

    raw = (
        "A changeset looks like this:\n"
        '```json\n[{"op": "add", "title": "EXAMPLE", "why": "illustration"}]\n```\n'
        "Here is the real one:\n"
        '```json\n[{"op": "add", "title": "REAL", "why": "asked for"}]\n```'
    )
    reply, changeset, _c, _cl = pm.chat(
        FakeMessagesListChatModel(responses=[AIMessage(content=raw)]), "ctx", [], "add"
    )
    assert [op["title"] for op in changeset] == ["REAL"]
    assert "EXAMPLE" in reply and "REAL" not in reply


def test_a_malformed_fenced_changeset_stays_visible() -> None:
    """Same rule as the unfenced case: nothing was extracted, so nothing is removed. A proposal
    that silently vanishes is the worse failure — the operator would see a reply with a hole in
    it and no way to know a proposal had been attempted."""
    from mosaera_agents import pm

    raw = 'Trying this.\n```json\n[{"op": "add", "title": ]]broken\n```'
    reply, changeset, _c, _cl = pm.chat(
        FakeMessagesListChatModel(responses=[AIMessage(content=raw)]), "ctx", [], "add"
    )
    assert changeset == []
    assert "broken" in reply


def test_a_fenced_object_is_not_a_changeset() -> None:
    """A changeset is an ARRAY of ops. A fenced object is some other thing the model wrote, and
    the charter/clarify proposals have their own tags for a reason."""
    from mosaera_agents import pm

    raw = 'Note.\n```json\n{"op": "add", "title": "not an array"}\n```'
    _reply, changeset, _c, _cl = pm.chat(
        FakeMessagesListChatModel(responses=[AIMessage(content=raw)]), "ctx", [], "?"
    )
    assert changeset == []


def test_an_empty_fenced_array_is_still_stripped() -> None:
    """The one case where "was extracted" and "yielded ops" diverge. A well-formed `[]` is a
    correctly-formatted empty proposal; leaking its raw JSON would punish the model for getting
    the format right. With nothing else in the reply, F48 then returns "" so the caller can
    surface a failed turn rather than a sentence that means nothing."""
    from mosaera_agents import pm

    reply, changeset, _c, _cl = pm.chat(
        FakeMessagesListChatModel(responses=[AIMessage(content="```json\n[]\n```")]),
        "ctx",
        [],
        "?",
    )
    assert changeset == []
    assert "[" not in reply
    assert reply == ""


def test_decompose_and_curate_still_accept_a_bare_array() -> None:
    """The boundary, stated by name. `_DECOMPOSE_SYSTEM` says "No prose outside the JSON" and
    `_CURATE_SYSTEM` says "Output ONLY the JSON array" — a bare array is the CORRECT output on
    both paths, so the shared `_extract_json_array` keeps its unfenced fallback. Only the chat
    prompt asks for a fence. A future tightening of the shared helper should fail here, with a
    name that says why."""
    from mosaera_agents import pm

    items = pm.decompose_brief(
        FakeMessagesListChatModel(
            responses=[AIMessage(content='[{"title": "A", "acceptance": "a"}]')]
        ),
        "brief",
        "outcome",
    )
    assert [i["title"] for i in items] == ["A"]

    ops = pm.curate_backlog(
        FakeMessagesListChatModel(
            responses=[AIMessage(content='[{"op": "delete", "id": 1, "why": "w"}]')]
        ),
        # (backlog, brief, instruction) — the order production uses at
        # `apps/api/mosaera_api/projects.py:296`. Both are interpolated into the prompt as
        # text, so passing them swapped still parsed at runtime and only mypy saw it.
        "- #1 t (todo)",
        "goal",
        "drop it",
    )
    assert [op["op"] for op in ops] == ["delete"]


def test_changeset_regex_has_no_catastrophic_backtracking() -> None:
    """A guard for future edits, not a fix: the pattern is unchanged apart from a capture group.
    Mirrors `test_charter_regex_has_no_catastrophic_backtracking` — the charter regex DID once
    backtrack quadratically (MR3 red-team), and the model-output path is human-blocking in
    pm_chat, so a jailbroken model could stall a worker."""
    import time

    from mosaera_agents.pm._proposals import _extract_changeset

    for probe in (
        "```json\n" + "x" * 60_000,  # opened, never reaches a bracket
        "```json\n[" + "y" * 60_000,  # opened array, never closed
    ):
        started = time.monotonic()
        ops, visible = _extract_changeset(probe)
        assert time.monotonic() - started < 1.0
        assert ops == [] and visible == probe  # refused, and left alone
