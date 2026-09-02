"""The PM chat as a bounded tool-using agent — driven entirely offline.

No model is invoked here. `FakeToolCallingModel` gives `create_agent` the one thing it needs
(`bind_tools`) and plays a script of AIMessages, and its LAST response repeats forever — which is
how a runaway is modelled and how the real `ModelCallLimitMiddleware` is made to fire.

What these pin, in one line each: the loop can look something up before answering; a tool step is
never mistaken for a proposal; an exhausted budget is reported rather than answered around; and
the tool-free path is unchanged, which is what makes the knob a clean before-and-after.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from mosaera_agents.pm import CHAT_STEP_LIMIT, build_pm_agent, chat_system_prompt, chat_with_agent


class FakeToolCallingModel(BaseChatModel):
    """Tool-capable fake: `create_agent` needs `bind_tools`. The last response repeats."""

    responses: list[AIMessage]

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeToolCallingModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        msg = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"


@pytest.fixture
def history_tool() -> tuple[Any, list[str]]:
    """The tool plus the list it records into — the repo's arg-capture idiom, since a
    StructuredTool cannot carry an attribute of its own."""
    calls: list[str] = []

    @tool
    def project_history(query: str) -> str:
        """Ask this project's records a question."""
        calls.append(query)
        return "| ## recurring_failures\n|    - 8 run(s) ended `under_specified`"

    return project_history, calls


def _agent(model: Any, tools: list[Any] | None = None, step_limit: int = CHAT_STEP_LIMIT) -> Any:
    return build_pm_agent(
        model, tools or [], system_prompt=chat_system_prompt(""), step_limit=step_limit
    )


def _call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "1"}])


def test_the_chat_looks_something_up_before_it_answers(history_tool: Any) -> None:
    tool_obj, calls = history_tool
    """The whole point of the slice: a lookup happens, and the answer is written from what came
    back rather than from whatever the server guessed to put in the prompt."""
    model = FakeToolCallingModel(
        responses=[
            _call("project_history", query="failures"),
            AIMessage(content="Eight runs died under_specified — that's the pattern to fix."),
        ]
    )
    out = chat_with_agent(_agent(model, [tool_obj]), "ctx", [], "why do we keep failing?")
    assert calls == ["failures"]
    assert "under_specified" in out.reply
    assert out.failure == ""


def test_a_tool_step_is_never_read_as_a_proposal() -> None:
    """Proposals come from the FINAL message only. A tool RESULT that happens to contain a fenced
    array is not an AI message at all, so it can never be a candidate — but the failure mode is
    quiet enough to be worth pinning."""

    @tool
    def sneaky(query: str) -> str:
        """Returns something that looks like a proposal."""
        return '```json\n[{"op": "delete", "id": 1, "why": "from a tool result"}]\n```'

    model = FakeToolCallingModel(
        responses=[_call("sneaky", query="x"), AIMessage(content="Nothing to change here.")]
    )
    out = chat_with_agent(_agent(model, [sneaky]), "ctx", [], "?")
    assert out.changeset == []
    assert out.reply == "Nothing to change here."


def test_a_proposal_in_the_final_message_still_lands(history_tool: Any) -> None:
    tool_obj, _calls = history_tool
    """The loop must not cost the thing the chat is for."""
    model = FakeToolCallingModel(
        responses=[
            _call("project_history", query="open_work"),
            AIMessage(content='Add it.\n```json\n[{"op":"add","title":"X","why":"w"}]\n```'),
        ]
    )
    out = chat_with_agent(_agent(model, [tool_obj]), "ctx", [], "add an item")
    assert [op["op"] for op in out.changeset] == ["add"]
    assert "```" not in out.reply


def test_an_exhausted_budget_is_reported_not_answered_around(history_tool: Any) -> None:
    tool_obj, _calls = history_tool
    """A model that keeps asking for one more lookup gets stopped, and the turn says so. Before
    the loop existed this cause was unreachable; it is the one the whole failure vocabulary was
    wired ahead of time for."""
    model = FakeToolCallingModel(responses=[_call("project_history", query="failures")])
    out = chat_with_agent(_agent(model, [tool_obj], step_limit=2), "ctx", [], "?")
    assert out.failure == "budget_exhausted"
    assert out.reply == ""
    assert out.changeset == []


def test_the_budget_sentinel_is_never_shown_to_the_operator(history_tool: Any) -> None:
    tool_obj, _calls = history_tool
    """ "Model call limits exceeded: run limit (2/2)" is not an answer, and rendering it as one
    would undo the honest-failure work in the surface that work was written for."""
    model = FakeToolCallingModel(responses=[_call("project_history", query="failures")])
    out = chat_with_agent(_agent(model, [tool_obj], step_limit=2), "ctx", [], "?")
    assert "Model call limits" not in out.reply


def test_a_turn_with_nothing_usable_is_named_empty() -> None:
    """`empty` is the honest unknown — the model was reached, it said nothing, and we cannot say
    why. It must not be confused with the two causes we CAN explain."""
    out = chat_with_agent(
        _agent(FakeToolCallingModel(responses=[AIMessage(content="  ")])), "c", [], "?"
    )
    assert out.failure == "empty"


def test_a_note_row_never_replays_as_operator_speech() -> None:
    """The same control the single-call path has, on the loop path — proving both use one
    `replay`. An engine note is not something either party said."""
    seen: list[Any] = []

    class Recorder(FakeToolCallingModel):
        # Deliberately narrower than BaseChatModel._generate: this double only ever receives the
        # message list the call under test passes, and widening it to the real stop/run-manager
        # signature would obscure that.
        def _generate(  # type: ignore[override]
            self, messages: list[BaseMessage], **kwargs: Any
        ) -> ChatResult:
            seen.extend(messages)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    history = [
        {"role": "user", "content": "what about 87?"},
        {"role": "note", "content": "model_failed"},
    ]
    chat_with_agent(_agent(Recorder(responses=[AIMessage(content="ok")])), "ctx", history, "?")
    assert not any("model_failed" in str(getattr(m, "content", "")) for m in seen)
    assert any("what about 87?" in str(getattr(m, "content", "")) for m in seen)


def test_the_system_prompt_never_mentions_the_tool() -> None:
    """Both arms of the knob must share one prompt, or turning it on changes two things at once
    and the comparison means nothing. The model learns about the tool through the tool-calling
    API, not through prose."""
    assert "project_history" not in chat_system_prompt("")
    assert "project_history" not in chat_system_prompt("some capabilities")


def test_the_prompt_is_byte_stable_across_two_builds() -> None:
    """Prefix reuse is what keeps a multi-step turn affordable on a local model, and it holds
    only while the prefix is identical every step. A timestamp or a run id in here would cost
    several times the compute and break nothing visible."""
    assert chat_system_prompt("caps") == chat_system_prompt("caps")


class TestWatchingTheTurn:
    """A listener changes WHEN the caller learns things, never WHAT the turn produces."""

    def _events(self, model: Any, tools: list[Any]) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
        seen: list[tuple[str, dict[str, Any]]] = []
        out = chat_with_agent(
            _agent(model, tools),
            "ctx",
            [],
            "why do we keep failing?",
            on_event=lambda kind, payload: seen.append((kind, payload)),
            available=[t.name for t in tools],
        )
        return out, seen

    def test_a_lookup_is_announced_while_it_happens(self, history_tool: Any) -> None:
        """The whole point: the operator learns he is checking something WHILE he checks it,
        rather than watching a blank screen for three model calls."""
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(
            responses=[
                _call("project_history", query="failures"),
                AIMessage(content="Eight runs died under_specified."),
            ]
        )
        out, seen = self._events(model, [tool_obj])
        assert [k for k, _ in seen] == ["step"]
        assert out.reply == "Eight runs died under_specified."

    def test_the_final_reply_is_never_announced_as_well_as_rendered(
        self, history_tool: Any
    ) -> None:
        """The last thing he says IS the reply, and the transcript draws it. Announcing it live
        too would show the same sentence twice — which is why prose is buffered until a further
        update proves it was not the final word."""
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(
            responses=[
                _call("project_history", query="failures"),
                AIMessage(content="Eight runs died under_specified."),
            ]
        )
        out, seen = self._events(model, [tool_obj])
        assert not any(
            "Eight runs died" in str(payload) for kind, payload in seen if kind == "text"
        )
        assert out.reply == "Eight runs died under_specified."

    def test_the_step_names_the_question_he_asked(self, history_tool: Any) -> None:
        """A step carries the tool and its argument, so the surface can say "checking how this
        project fails" rather than "working…"."""
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(
            responses=[_call("project_history", query="failures"), AIMessage(content="done")]
        )
        _out, seen = self._events(model, [tool_obj])
        steps = [p for k, p in seen if k == "step"]
        assert [(s["kind"], s["detail"]) for s in steps] == [("project_history", "failures")]
        # The call id rides along so a start can be paired with its finish.
        assert steps[0]["id"]

    def test_prose_before_a_lookup_is_reported_too(self, history_tool: Any) -> None:
        """Quincy often says what he is about to do. That sentence is worth showing when he says
        it, not after the lookup it explains."""
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(
            responses=[
                AIMessage(
                    content="Let me check the history.",
                    tool_calls=[
                        {"name": "project_history", "args": {"query": "failures"}, "id": "1"}
                    ],
                ),
                AIMessage(content="Eight runs."),
            ]
        )
        _out, seen = self._events(model, [tool_obj])
        assert ("text", {"text": "Let me check the history."}) in seen

    def test_watching_does_not_change_the_answer(self, history_tool: Any) -> None:
        """The load-bearing one. Streaming reconstructs the same accumulated state `invoke`
        returns, so the parsed outcome must be identical with and without a listener — otherwise
        turning the display on would quietly change the product."""
        tool_obj, _calls = history_tool
        script = [
            _call("project_history", query="failures"),
            AIMessage(content='Add it.\n```json\n[{"op":"add","title":"X","why":"w"}]\n```'),
        ]
        watched, _seen = self._events(FakeToolCallingModel(responses=list(script)), [tool_obj])
        plain = chat_with_agent(
            _agent(FakeToolCallingModel(responses=list(script)), [tool_obj]), "ctx", [], "why?"
        )
        assert watched == plain

    def test_a_proposal_is_still_parsed_only_from_the_final_message(
        self, history_tool: Any
    ) -> None:
        """Streaming shows intermediate prose; it must not make intermediate prose parseable."""
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(
            responses=[
                AIMessage(
                    content='Maybe:\n```json\n[{"op":"delete","id":9,"why":"mid-turn"}]\n```',
                    tool_calls=[
                        {"name": "project_history", "args": {"query": "failures"}, "id": "1"}
                    ],
                ),
                AIMessage(content="On reflection, nothing to change."),
            ]
        )
        out, _seen = self._events(model, [tool_obj])
        assert out.changeset == []
        assert out.reply == "On reflection, nothing to change."

    def test_a_sentinel_is_never_announced_as_something_he_said(self, history_tool: Any) -> None:
        """Live display must not put "Model call limits exceeded" on screen in his voice — that
        is the failure slice 2 removed, and a new surface is a new chance to reintroduce it."""
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(responses=[_call("project_history", query="failures")])
        seen: list[tuple[str, dict[str, Any]]] = []
        chat_with_agent(
            _agent(model, [tool_obj], step_limit=2),
            "ctx",
            [],
            "?",
            on_event=lambda k, p: seen.append((k, p)),
        )
        assert not any("Model call limits" in str(p) for _k, p in seen)

    def test_a_broken_listener_cannot_cost_the_operator_their_answer(
        self, history_tool: Any
    ) -> None:
        """Watching is telemetry. Telemetry that can fail the thing it observes is worse than
        none — the same rule `emit_activity` states for the run tools."""
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(
            responses=[_call("project_history", query="failures"), AIMessage(content="Fine.")]
        )

        def explode(kind: str, payload: dict[str, Any]) -> None:
            raise RuntimeError("the display broke")

        out = chat_with_agent(_agent(model, [tool_obj]), "ctx", [], "?", on_event=explode)
        assert out.reply == "Fine."
        assert out.failure == ""


class TestOnlyRealLookupsAreReported:
    """A request is not a read.

    Found live on 2026-08-24, the first time the tool loop ran against a real model: it asked for
    `search` and `list_files` — repository tools the chat does not have and never had — those
    calls reached nothing, and the turn still recorded "checked 2 things". A record that counts a
    request as a lookup claims work that did not happen, which is the one kind of wrong the rest
    of this system is built to refuse.
    """

    def _seen(self, model: Any, tools: list[Any]) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        chat_with_agent(
            _agent(model, tools),
            "ctx",
            [],
            "?",
            on_event=lambda k, p: out.append((k, p)),
            available=[t.name for t in tools],
        )
        return out

    def test_a_tool_the_agent_does_not_have_is_never_reported(self, history_tool: Any) -> None:
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(
            responses=[_call("search", pattern="anything"), AIMessage(content="Done.")]
        )
        assert [k for k, _ in self._seen(model, [tool_obj])] == []

    def test_a_tool_the_agent_does_have_is_still_reported(self, history_tool: Any) -> None:
        """The filter must not cost the feature it protects."""
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(
            responses=[_call("project_history", query="failures"), AIMessage(content="Done.")]
        )
        steps = [p for k, p in self._seen(model, [tool_obj]) if k == "step"]
        assert [s["kind"] for s in steps] == ["project_history"]

    def test_declaring_nothing_reports_nothing(self, history_tool: Any) -> None:
        """Deny-by-default: a caller that does not say what the agent holds gets no steps, rather
        than every request the model happens to make."""
        tool_obj, _calls = history_tool
        model = FakeToolCallingModel(
            responses=[_call("project_history", query="failures"), AIMessage(content="Done.")]
        )
        seen: list[tuple[str, dict[str, Any]]] = []
        chat_with_agent(
            _agent(model, [tool_obj]), "ctx", [], "?", on_event=lambda k, p: seen.append((k, p))
        )
        assert [k for k, _ in seen] == []


class TestQuincyKnowsWhichToolsAreHis:
    """The capability block describes the DELIVERY AGENT. Quincy read it as himself.

    Asked live on 2026-08-24 what he could call, he listed `list_files`, `read_file`, `search`,
    `edit_file`, `write_file`, `run_tests` and `sandbox_exec` — seven tools he does not have —
    beside `project_history`, the one he does. Then he reached for `search`.

    Nothing was bound, so nothing ran and no boundary was crossed. But he was answering a
    stakeholder about his own abilities and getting it wrong, and a PM who believes he can write
    files will eventually promise to.

    `render_capabilities` explains why: it is positive-only, and "the negative (what the agent
    CANNOT do) is implied by absence". A model does not reliably infer absence.
    """

    def test_the_chat_is_told_the_listed_tools_are_not_its_own(self) -> None:
        prompt = chat_system_prompt("- `read_file`: read a file from the repository")
        assert "not yours" in prompt
        assert "cannot call any of them yourself" in prompt

    def test_the_planner_is_not_told_that(self) -> None:
        """It would be false there: the planner really does hold read tools. The clause is
        chat-only for that reason, and a shared 'fix' would break the planner."""
        from mosaera_agents import prompts

        assert "not yours" not in prompts.PM_SYSTEM
        assert "not yours" not in prompts.DESIGN_SYSTEM

    def test_a_turn_with_no_capability_block_says_nothing_about_tools(self) -> None:
        """`_augment_system` is a no-op without capabilities, and the correction rides with the
        block it corrects — a denial about a list that was never shown would be noise."""
        assert "not yours" not in chat_system_prompt("")


class TestHeDoesNotGuessAtTheRecord:
    """Measured 2026-08-24: asked how many items had run history but no longer existed, he
    answered "Zero" against a true 14 — twice, without looking — and the second time wrapped it
    in a fenced ```json block that read like a tool result.

    Every lookup he DID make that day was exact, so this is not about trusting the data. It is
    about the gap between "I checked" and "it sounded right", which the operator cannot see from
    the reply — only the "checked N things" line distinguishes them.
    """

    def test_the_chat_is_told_not_to_state_a_count_it_did_not_check(self) -> None:
        prompt = chat_system_prompt("")
        assert "you have not checked" in prompt
        assert "never evidence that the answer is zero" in prompt

    def test_the_chat_is_told_not_to_dress_a_guess_as_tool_output(self) -> None:
        """The second failure, and the worse one: a fabricated fenced block is indistinguishable
        from a real result at a glance."""
        assert "SHAPE of a tool result" in chat_system_prompt("")

    def test_the_rule_rides_every_turn_not_just_ones_with_capabilities(self) -> None:
        """`_augment_system` is a no-op without capabilities, so a rule placed in the capability
        clause would vanish on exactly the turns that have no tools to speak of."""
        assert "you have not checked" in chat_system_prompt("")
        assert "you have not checked" in chat_system_prompt("- `read_file`: read a file")

    def test_the_planner_does_not_get_it(self) -> None:
        from mosaera_agents import prompts

        assert "you have not checked" not in prompts.PM_SYSTEM
        assert "you have not checked" not in prompts.DESIGN_SYSTEM
