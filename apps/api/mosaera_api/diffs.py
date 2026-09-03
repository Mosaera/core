"""Pure diff/report helpers shared by the runs and projects routers.

Leaf module (no app imports) so both ``routes.runs`` and the still-inline
projects endpoints can use them without an import cycle back through ``app``.
"""

from __future__ import annotations

from typing import Any


def _changed_files_from_diff(diff: str) -> list[str]:
    files: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.append(path)
    return files


def _mr_report(detail: dict[str, Any]) -> str:
    parts = []
    for kind, heading in (("summary", "What the Coder did"), ("review", "Reviewer")):
        content = next((d["content"] for d in detail["decisions"] if d["kind"] == kind), "")
        if content:
            parts.append(f"### {heading}\n{content}")
    return "\n\n".join(parts) or "(no summary)"
