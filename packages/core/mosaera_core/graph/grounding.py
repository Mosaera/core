"""Deterministic read helpers: design-grounding, planning overviews, and the
reviewer's machine-computed quality evidence. No model calls — cheap priors that a
tool-using agent supplements on demand."""

from __future__ import annotations

import hashlib
import re

from mosaera_core.doctrine import load_global_doctrine
from mosaera_core.graph.context import RunContext
from mosaera_core.mapview import render_project_map
from mosaera_core.quality import changed_python_files, function_stats, quality_findings
from mosaera_core.tools.repo import Workspace


def _trunc(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... (truncated at {limit} chars)"


# Design-grounding (#3 / P2): the design stage is asked to name real files and
# signatures but only ever saw a filename list. These deterministically select and
# read the files the PLAN references so the design grounds in actual code — no model
# call, memoized by (tree_hash, plan) like the other cached evidence (ADR-0003).
# Trimmed now that the PM reads on demand (EYES): the deterministic grounding is a
# cheap prior, not the sole source, so a tool-using planner supplements it by reading
# the files it actually needs — keeping total planner context roughly flat.
_GROUNDING_FILES = 4
_GROUNDING_PER_FILE = 2000


def plan_named_files(listing: list[str], plan: str, limit: int = _GROUNDING_FILES) -> list[str]:
    """The repo files the plan references, most-specific first: a full-path mention
    beats a bare filename, and a bare filename must have an extension and be long
    enough to avoid matching common words."""
    ranked: list[tuple[int, str]] = []
    for path in listing:
        if path in plan:
            ranked.append((2, path))
            continue
        base = path.rsplit("/", 1)[-1]
        if "." in base and len(base) >= 5 and re.search(rf"\b{re.escape(base)}\b", plan):
            ranked.append((1, path))
    ranked.sort(key=lambda r: (-r[0], len(r[1])))
    out: list[str] = []
    for _, path in ranked:
        if path not in out:
            out.append(path)
        if len(out) >= limit:
            break
    return out


def _review_quality_evidence(workspace: Workspace, diff: str) -> str:
    """Objective, machine-computed quality signal on the CHANGED files, handed to the
    reviewer so it verifies structural CHECKs against DATA, not eyeballing: deterministic
    complexity/type/style findings plus per-function body-statement counts (a refactor's
    "keep it short/decomposed" CHECK is judged on the real numbers). "" when the change
    touches no python."""
    changed = [f for f in changed_python_files(diff) if (workspace.root / f).is_file()]
    if not changed:
        return ""
    findings = quality_findings(workspace, changed)
    parts: list[str] = []
    for dim in ("Complexity", "Types", "Style"):
        msgs = findings.get(dim, [])
        if msgs:
            parts.append(f"{dim}: " + "; ".join(msgs[:5]))
    sizes = function_stats(workspace, changed)
    if sizes:
        parts.append("Function sizes: " + "; ".join(sizes[:10]))
    return "\n".join(parts)


def build_grounding(workspace: Workspace, plan: str) -> str:
    """A `## Relevant file contents` block for the files the plan names (capped;
    binaries skipped), or "" when none match."""
    parts: list[str] = []
    for rel in plan_named_files(workspace.file_listing(), plan):
        try:
            text = (workspace.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in text[:1024]:  # binary-ish → skip
            continue
        parts.append(f"### {rel}\n```\n{text[:_GROUNDING_PER_FILE]}\n```")
    return "## Relevant file contents\n" + "\n\n".join(parts) if parts else ""


def planning_overview(ctx: RunContext) -> str:
    # The repo overview both planning and design see: the memoized file listing
    # (#23) prefixed with the shared project context (#26 — brief + backlog +
    # what sibling items already built), so both plan with project awareness.
    key = ("overview", ctx.workspace.tree_hash())
    overview = ctx.evidence_memo.get(key)
    if overview is None:
        overview = "\n".join(ctx.workspace.file_listing(limit=120))
        ctx.evidence_memo[key] = overview
    context = ctx.project_context or (
        f"## Project brief\n{ctx.project_brief}" if ctx.project_brief else ""
    )
    body = f"{context}\n\n## Repository files\n{overview}" if context else overview
    body = _with_project_map(ctx, body)
    # Prepend the trusted global planning doctrine (static, cached) so plan AND
    # design (which calls this via grounded_overview) follow it. The kill-switch
    # drops it for a tiny-context model.
    doctrine = load_global_doctrine() if ctx.settings.doctrine_enabled else ""
    return f"{doctrine}\n\n{body}" if doctrine else body


def _with_project_map(ctx: RunContext, body: str) -> str:
    """Append the UNTRUSTED project map for gap-analysis scoping when enabled (#42, ADR-0047 §2).

    Read FRESH — the map changes independently of the tree, so it is deliberately NOT under the
    ``tree_hash`` memo above. The map is a hypothesis generator, never evidence: it informs SCOPING
    and never reaches the gate (``packages/policies`` cannot import it). It is a SEPARATE block from
    the trusted doctrine, and a first run with no/empty map degrades to the cold look and SAYS so
    (§6). No project (a CLI/repo run) or no DB ⇒ unchanged body.
    """
    if not (ctx.settings.onboarding_map_scoping and ctx.project_id and ctx.memory is not None):
        return body
    block = render_project_map(ctx.memory.list_map_dimensions(ctx.project_id))
    if not block:
        return f"{body}\n\n## Project map\nNo project map yet — planning from a cold first look."
    return f"{body}\n\n{block}"


def grounded_overview(ctx: RunContext, plan: str) -> str:
    # planning_overview (filenames) + the CONTENTS of the files the plan names,
    # so the design grounds signatures in real code. Memoized by (tree, plan):
    # deterministic, no model call, recomputed only when the tree or plan changes.
    key = ("grounding", ctx.workspace.tree_hash(), hashlib.sha256(plan.encode()).hexdigest())
    grounding = ctx.evidence_memo.get(key)
    if grounding is None:
        grounding = build_grounding(ctx.workspace, plan)
        ctx.evidence_memo[key] = grounding
    base = planning_overview(ctx)
    return f"{base}\n\n{grounding}" if grounding else base
