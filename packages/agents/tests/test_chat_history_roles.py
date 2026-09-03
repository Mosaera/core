"""A failure note is not speech, and must never be replayed to the model.

The chat transcript carries three kinds of row: what the operator said, what Quincy said, and an
engine `note` recording that a turn did not complete. Only the first two are utterances. Replaying
the third would teach the conversation its own failures as if someone had spoken them — and,
because history construction used to send everything that was not `role == "pm"` as a HUMAN turn,
it would arrive as if the OPERATOR had said it.

The API filters (`mosaera_memory.conversation_turns`); these pin the agents-side backstop, which
is what holds if a future caller forgets. Agents never imports memory, so the roles are literals
on both sides — that is what makes a test the joint rather than an import.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from mosaera_agents.pm import chat, synthesize_understanding


def _captured(history: list[dict[str, str]]) -> list[Any]:
    seen: list[Any] = []

    class Recorder(FakeMessagesListChatModel):
        # Deliberately narrower than BaseChatModel.invoke: this double only ever receives
        # the message list the call under test passes, and widening it to the real
        # PromptValue|str|Sequence union would obscure that.
        def invoke(self, messages: Any, *a: Any, **k: Any) -> Any:  # type: ignore[override]
            seen.extend(messages)
            return AIMessage(content="ok")

    chat(Recorder(responses=[]), "ctx", history, "and now?")
    return seen


def test_a_failure_note_never_reaches_the_model() -> None:
    history = [
        {"role": "user", "content": "what should we do about 87?"},
        {"role": "note", "content": "model_failed"},
        {"role": "pm", "content": "let's split it"},
    ]
    bodies = [str(getattr(m, "content", "")) for m in _captured(history)]
    assert not any("model_failed" in b for b in bodies), "the engine note was replayed"
    assert any("what should we do about 87?" in b for b in bodies)
    assert any("let's split it" in b for b in bodies)


def test_an_unknown_role_is_dropped_rather_than_read_as_the_operator() -> None:
    """Deny-by-default. The old `else` made every unrecognised role a HUMAN turn, so any row type
    added later would silently start speaking in the operator's voice."""
    bodies = [
        str(getattr(m, "content", ""))
        for m in _captured([{"role": "something_new", "content": "SURPRISE"}])
    ]
    assert not any("SURPRISE" in b for b in bodies)


def test_the_two_speakers_still_get_their_own_message_types() -> None:
    """The filter must not cost the distinction it is protecting."""
    seen = _captured([{"role": "user", "content": "U"}, {"role": "pm", "content": "P"}])
    kinds = {str(getattr(m, "content", "")): m.type for m in seen}
    assert kinds["U"] == "human" and kinds["P"] == "ai"


def test_brief_synthesis_never_quotes_a_failure_note_as_quincy() -> None:
    """The worst version of this leak: `synthesize_understanding` is fed the WHOLE project
    transcript and its output becomes the durable project brief. Attributing an engine failure to
    Quincy there would write it into the project's own statement of intent."""
    seen: list[Any] = []

    class Recorder(FakeMessagesListChatModel):
        # Deliberately narrower than BaseChatModel.invoke: this double only ever receives
        # the message list the call under test passes, and widening it to the real
        # PromptValue|str|Sequence union would obscure that.
        def invoke(self, messages: Any, *a: Any, **k: Any) -> Any:  # type: ignore[override]
            seen.extend(messages)
            return AIMessage(content="a brief")

    synthesize_understanding(
        Recorder(responses=[]),
        [
            {"role": "user", "content": "build a ledger"},
            {"role": "note", "content": "model_failed"},
        ],
        "overview",
        "",
        "",
    )
    transcript = "\n".join(str(getattr(m, "content", "")) for m in seen)
    assert "Quincy: model_failed" not in transcript
    assert "model_failed" not in transcript
    assert "build a ledger" in transcript
