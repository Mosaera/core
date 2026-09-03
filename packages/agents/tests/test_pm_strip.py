from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from mosaera_agents.pm import _FALLBACK_PLAN, plan_task, strip_preamble


def test_strips_leading_deliberation_before_numbered_plan() -> None:
    text = (
        "We don't have the file contents yet, but let's assume a calc module.\n"
        "Maybe the bug is in subtract. Let's guess.\n"
        "1. Open calc.py\n"
        "2. Fix the return statement\n"
    )
    out = strip_preamble(text)
    assert out.startswith("1. Open calc.py")
    assert "let's assume" not in out


def test_strips_before_plan_header() -> None:
    text = "Thinking out loud about the repo...\n\n**Implementation Plan**\n1. Do the thing\n"
    out = strip_preamble(text)
    assert out.startswith("**Implementation Plan**")


def test_clean_plan_unchanged() -> None:
    text = "1. Open calc.py\n2. Fix it\n"
    assert strip_preamble(text) == text.strip()


def test_no_marker_returned_as_is() -> None:
    text = "Just a prose answer with no numbered plan or header."
    assert strip_preamble(text) == text.strip()


def test_empty_model_output_falls_back() -> None:
    # Reasoning model routed everything to its thinking channel -> empty content.
    model = FakeMessagesListChatModel(responses=[AIMessage(content="")])
    plan = plan_task(model, "fix the bug", "calc.py")
    assert plan == _FALLBACK_PLAN


# --- WHY the planner fell back (F39 / issue #71) -----------------------------------------------
#
# Three very different failures collapse into the same silent `_FALLBACK_PLAN`, and the graph used
# to recover the fact by comparing the text to the constant — by which point the cause was gone.
# Measured 2026-08-07: the planner spent all 12 of its model calls reading the repo, and the run
# told the operator their backlog ITEM needed clarification. Each cause demands a different human
# response, so each must produce a different answer here.

from types import SimpleNamespace  # noqa: E402

from mosaera_agents.pm import fallback_reason  # noqa: E402


def _ai(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="ai", content=text)


def test_budget_exhaustion_is_named() -> None:
    """The ModelCallLimitMiddleware sentinel — the measured 2026-08-07 cause."""
    msgs = [_ai("let me look around"), _ai("Model call limits exceeded: run limit (12/12)")]
    assert fallback_reason({"messages": msgs}) == "budget_exhausted"


def test_a_transport_failure_is_named() -> None:
    """F39's original signature: the retry middleware continues rather than raising, leaving the
    error in the messages as the ONLY evidence the model was never reached."""
    msgs = [
        _ai("Model call failed after 3 attempts with ResponseError: <html>502 Bad Gateway</html>")
    ]
    assert fallback_reason({"messages": msgs}) == "model_failed"


def test_no_marker_is_empty_not_a_guess() -> None:
    """`empty` is the honest unknown — and the ONLY case where blaming the item is fair."""
    assert fallback_reason({"messages": []}) == "empty"
    assert fallback_reason({"messages": [_ai("")]}) == "empty"


def test_the_three_causes_are_distinguishable() -> None:
    """The property that matters: they must not collapse. If any two of these ever compare equal,
    the operator is back to guessing between 'raise a budget' and 'restart a server'."""
    budget = fallback_reason({"messages": [_ai("Model call limits exceeded: run limit (12/12)")]})
    transport = fallback_reason({"messages": [_ai("Model call failed after 3 attempts")]})
    empty = fallback_reason({"messages": []})
    assert len({budget, transport, empty}) == 3


# --- the capture, and the plan the engine used to throw away (#71, F39) ------------------------
#
# `reviewer.py:166-183` already learned this with this exact model: gpt-oss:20b routinely leaves
# `content` EMPTY and puts the whole answer in the reasoning channel, and a content-only read
# false-parked ~75% of MCB-21 runs WHOSE CODE WAS CORRECT. The PM planner was the last
# content-only consumer in the engine.

from typing import Any  # noqa: E402

from mosaera_agents.messages import fallback_evidence  # noqa: E402
from mosaera_agents.pm import plan_with_agent_detailed  # noqa: E402


def _reasoning_msg(reasoning: str, content: str = "", **meta: Any) -> AIMessage:
    m = AIMessage(content=content, additional_kwargs={"reasoning_content": reasoning})
    if meta:
        m.response_metadata = dict(meta)
    return m


class _FakeAgent:
    """A compiled-agent stand-in: returns a fixed message list from .invoke."""

    def __init__(self, *messages: Any) -> None:
        self._messages = list(messages)

    def invoke(self, _payload: Any, _config: Any = None) -> dict[str, Any]:
        return {"messages": self._messages}


def _fake(*messages: Any) -> Any:
    """Typed as Any: the real parameter is a compiled Runnable, and a stub only needs .invoke."""
    return _FakeAgent(*messages)


_PLAN = "1. Scope status to the current month.\n2. Delete the fallback.\n3. Run the tests."


def test_a_plan_written_to_the_reasoning_channel_is_rescued() -> None:
    """THE fix. Before this the plan below was discarded and the coder got a three-line stub."""
    out = plan_with_agent_detailed(_fake(_reasoning_msg(_PLAN)), "t", "(files)")
    assert out.plan == _PLAN
    assert out.rescued is True
    assert out.reason == ""  # not a fallback at all


def test_shapeless_reasoning_is_NOT_rescued() -> None:
    """The one-sidedness pin, and the reason this is narrower than the reviewer's version:
    handing the coder a stream of deliberation as its marching orders is worse than falling back."""
    musing = "We need to replace lines 147-170. Let me look at the file again. Hmm."
    out = plan_with_agent_detailed(_fake(_reasoning_msg(musing)), "t", "(files)")
    assert out.plan.startswith("1. Inspect the relevant files.")  # the fallback
    assert out.rescued is False
    assert out.reason == "empty"


def test_content_present_is_byte_identical_to_before() -> None:
    out = plan_with_agent_detailed(_fake(AIMessage(content=_PLAN)), "t", "(files)")
    assert out.plan == _PLAN
    assert out.rescued is False
    assert out.evidence == ""  # no fallback ⇒ nothing to explain


def test_a_fallback_carries_the_raw_output() -> None:
    """The capture. `empty` was a dead end: diagnosing one such run took three synthetic probes
    against the live endpoint, none of which reproduced it — nothing recorded the real response."""
    msg = _reasoning_msg("thinking hard", content="", done_reason="length", eval_count=716)
    out = plan_with_agent_detailed(_fake(msg), "t", "(files)")
    assert out.plan.startswith("1. Inspect the relevant files.")
    assert "done_reason='length'" in out.evidence  # the field that separates blown-context
    assert "content=''" in out.evidence  # ...from a model that finished and said nothing
    assert "thinking hard" in out.evidence


def test_the_evidence_distinguishes_empty_from_whitespace() -> None:
    """`''` and `'   '` mean different things and read identically without the repr."""
    ev = fallback_evidence({"messages": [AIMessage(content="   ")]})
    assert "content='   '" in ev


def test_the_evidence_is_capped() -> None:
    huge = _reasoning_msg("x" * 500_000, content="y" * 500_000)
    ev = fallback_evidence({"messages": [huge]})
    assert len(ev) <= 4_000
    assert "elided" in ev  # and says so, rather than silently truncating


def test_the_evidence_survives_a_pure_tool_call_message() -> None:
    """A message with no text at all must not blow up the capture."""
    ev = fallback_evidence({"messages": [AIMessage(content="", tool_calls=[])]})
    assert "content_len=0" in ev


def test_the_budget_sentinel_is_never_rescued_as_a_plan() -> None:
    """The middleware's sentinel is injected as content; it must never become the plan."""
    sentinel = AIMessage(content="Model call limits exceeded: run limit (20/20)")
    out = plan_with_agent_detailed(_fake(sentinel), "t", "(files)")
    assert out.plan.startswith("1. Inspect the relevant files.")
    assert out.reason == "budget_exhausted"


def test_the_transport_sentinel_is_never_returned_as_a_plan() -> None:
    """The sibling of the budget case above, and the more dangerous of the two.

    `ModelRetryMiddleware(on_failure="continue")` leaves its failure text in the message list as
    an ORDINARY AI message so the run degrades instead of crashing. `_last_ai_text` skipped only
    the budget sentinel, so that text came back as the plan — and because `plan_is_fallback`
    compares against `_FALLBACK_PLAN`, the turn did not count as a fallback either: no reason was
    recorded, `plan_fallback_reason` never fired, and the coder received
    "Model call failed after 3 attempts with ResponseError: <html>… 502 …" as its instructions.

    `_rescued_from_reasoning` and `fallback_reason` both test for this sentinel; `_last_ai_text`
    was the only one of the three that did not, which is what makes it an oversight rather than a
    decision.
    """
    sentinel = AIMessage(
        content="Model call failed after 3 attempts with ResponseError: <html>502</html>"
    )
    out = plan_with_agent_detailed(_fake(sentinel), "t", "(files)")
    assert "502" not in out.plan and "Model call failed" not in out.plan
    assert out.plan == _FALLBACK_PLAN
    assert out.reason == "model_failed"
