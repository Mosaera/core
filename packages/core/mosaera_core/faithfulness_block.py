"""The repair checklist rendered from the detector's findings.

Lifted out of `_proctor_authoring` because that module sat at exactly its 500-line ceiling and
the loosen-only repair mode (#129) had nowhere to go. Self-contained by nature: it takes
findings and returns prompt text, and touches no run state.
"""

from __future__ import annotations

from mosaera_core.faithfulness import OverstrictFinding


def _faithfulness_block(findings: list[OverstrictFinding]) -> str:
    """Render the detector's findings as an explicit repair checklist, or "" when there are none."""
    if not findings:
        return ""
    lines = [
        "",
        "## Assertions to repair (deterministically detected)",
        "These authored assertions pin incidental detail the task left OPEN (exact whitespace, a "
        "rendering literal, a private symbol name), are mutually contradictory, pin the SPELLING "
        "of source code (which `ruff format` rewrites after you author, so the test can never "
        "pass), or assert nothing at all (so the test can never fail). For EACH, edit the test to "
        "assert only what the task states — UNLESS the task itself pins that exact value:",
    ]
    for f in findings:
        lines.append(f"- `{f.file}:{f.line}` [{f.kind}] `{f.snippet}` — {f.suggestion}")
    return "\n\n".join(("", "\n".join(lines)))
