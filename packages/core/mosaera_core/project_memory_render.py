"""Turn a project-memory ``Answer`` into text a person or a model can read.

One renderer, two callers: the ``mosaera-memory`` CLI and the read-only history tool. They
differ only in where the text goes and how much of it they want, so they differ only in their
arguments — a second copy would drift the day someone fixes a wording bug in one of them.

Not to be confused with ``pm_sections.project_memory_block``, which is a different thing on
purpose: that one builds the STANDING prompt block (its own headings, three findings, a preamble
telling Quincy the block is a summary). This one answers a question that was asked.
"""

from __future__ import annotations

from mosaera_core.project_memory import Answer

#: Detail fields worth showing: the acceptance text that failed, the exemplar behind a count.
#: Anything else in ``detail`` is machine bookkeeping and would only crowd the reading.
_SHOWN_DETAIL = ("acceptance", "example_reason")


def render_answer(
    answer: Answer,
    *,
    limit: int,
    # Run ids are long and there are many; item ids are short and, for `orphaned_history`, they
    # ARE the answer. Asked live to list every orphaned item, Quincy could only give eight and
    # said so — honestly, but the cap was mine and it truncated the one answer that is a list.
    run_ids: int = 4,
    item_ids: int = 30,
    detail_chars: int = 150,
    more_hint: str = "",
) -> str:
    """One answer, rendered. ``more_hint`` completes the "N more" line when findings are cut.

    The truncation line is not decoration. A reader who sees three findings and no note cannot
    tell "that is all there is" from "that is all we showed", and those are opposite facts about
    the project. Every caller must say which it is.
    """
    out = [f"\n## {answer.query}"]
    if answer.note:
        out.append(f"   {answer.note}")
    for finding in answer.findings[:limit]:
        out.append(f"   - {finding.summary}")
        runs = finding.evidence_runs
        if runs:
            shown = ", ".join(runs[:run_ids])
            more = f" (+{len(runs) - run_ids} more)" if len(runs) > run_ids else ""
            out.append(f"       runs: {shown}{more}")
        # Item ids, for the same reason run ids are shown: a count without the ids behind it
        # cannot be acted on or checked. `orphaned_history` is the case that proves it — asked
        # live which items had lost their history, Quincy could only answer "14 records, ids not
        # provided in the output", because they were computed here and then dropped before he saw
        # them. He was right, and precise about the limit; the limit was ours.
        items = finding.evidence_items
        if items:
            shown = ", ".join(f"#{i}" for i in items[:item_ids])
            more = f" (+{len(items) - item_ids} more)" if len(items) > item_ids else ""
            out.append(f"       items: {shown}{more}")
        for key, value in finding.detail.items():
            if key in _SHOWN_DETAIL and value:
                text = " ".join(str(value).split())
                clipped = f"{text[:detail_chars]}{'…' if len(text) > detail_chars else ''}"
                out.append(f"       {key}: {clipped}")
    hidden = len(answer.findings) - limit
    if hidden > 0:
        tail = f"; {more_hint}" if more_hint else ""
        out.append(f"   … {hidden} more finding(s){tail}")
    return "\n".join(out) + "\n"
