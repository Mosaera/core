"""The coder/reviewer/tester repo toolset — ``build_repo_tools``.

Every tool is bound to one ``Workspace`` clone and enforces the deterministic guards
(path escape, write scope / protected paths, churn, the run_tests repeat limit) at the
tool layer, not via prompt guidance. ``build_repo_tools`` is the single factory; the
graph wires the returned tools into the implement node. The PM-facing capability surface
(``describe_coder_capabilities``) lives in ``_capabilities``.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Collection, Sequence
from typing import Any

from langchain_core.tools import BaseTool, tool

from mosaera_core.progress import fingerprint
from mosaera_core.sandbox import SandboxWorker
from mosaera_core.tools.repo._activity import diff_against_disk as _diff_against_disk
from mosaera_core.tools.repo._activity import edit_diff as _edit_diff
from mosaera_core.tools.repo._activity import emit_activity as _emit_activity
from mosaera_core.tools.repo._activity import gate_content as _gate_content
from mosaera_core.tools.repo._activity import note_weakening as _note_weakening
from mosaera_core.tools.repo._envfacts import environment_facts
from mosaera_core.tools.repo._exec import build_sandbox_exec
from mosaera_core.tools.repo._hints import STUCK_HINT as _STUCK_HINT
from mosaera_core.tools.repo._hints import STUCK_HINT_WITH_DELETE as _STUCK_HINT_WITH_DELETE
from mosaera_core.tools.repo._read import _MAX_READ_CHARS as _MAX_READ_CHARS
from mosaera_core.tools.repo._read import windowed_read as _windowed_read
from mosaera_core.tools.repo._scratch import disallowed_scratch as _disallowed_scratch
from mosaera_core.tools.repo._scratch import under_scratch
from mosaera_core.tools.repo.workspace import PathEscapeError, Workspace

_MAX_SEARCH_RESULTS = 100
# ReDoS guardrails for the agent-supplied regex in `search` (runs host-side).
# The line cap bounds per-match input; the wall-clock deadline bounds the
# multi-file/line amplification and returns control. NOTE: neither can interrupt
# a single catastrophic-backtracking match mid-flight — the complete fix is a
# linear-time engine (re2) or routing search through the sandbox's ripgrep.
_MAX_SEARCH_LINE = 2_000
_SEARCH_DEADLINE_S = 5.0


def build_repo_tools(
    workspace: Workspace,
    sandbox: SandboxWorker,
    test_cmd: Sequence[str] | None = None,
    approval_gate: bool = True,
    install: bool = True,
    install_timeout: int | None = None,
    allow_delete: bool = False,
    test_repeat_limit: int = 3,
    write_prefix: str | None = None,
    protected_paths: Collection[str] = frozenset(),
    enable_exec: bool = False,
    enable_scratch: bool = False,
    operator_sanctioned: dict[str, str] | None = None,
    coder_validation: dict[str, str] | None = None,
    exec_degradations: dict[str, int] | None = None,
    exec_usage: dict[str, int] | None = None,
    actor: str = "Coder",
) -> list[BaseTool]:
    """Build the repo toolset bound to one workspace clone.

    ``actor`` names WHO is asking, in the approval summaries. It defaults to the coder, but the
    Proctor gets its own toolset (``write_prefix="tests/"``) and every gate it raised still read
    "Coder wants to write" — misattributing the one separation ADR-0013 exists to enforce, at the
    exact moment the operator is deciding whether to allow a test write.

    ``approval_gate=True`` routes every ``write_file`` through the human
    approval gate (packages/policies). Tests always run through the sandbox.
    ``allow_delete=True`` adds a human-gated ``delete_file`` — an opt-in,
    admin-enabled capability (see Settings.delete_tool_enabled); off by default.
    ``test_repeat_limit`` bounds how many times ``run_tests`` may return the SAME
    failure within one implement session before it stops the coder and tells it to
    yield (a within-node token guard; a real edit resets the count).

    Strict separation of duties (ADR-0013): ``write_prefix`` restricts this
    toolset's writes/edits to that directory (e.g. the tester may only touch
    ``tests/``); ``protected_paths`` are files this toolset may NOT write, edit, or
    delete (e.g. the coder is refused on the tester-authored test files). Both are
    deterministic tool-level guards, not prompt guidance.

    ``operator_sanctioned`` (F63, #65) is a SHARED MUTABLE map the graph also holds — the same
    ownership shape as ``protected_paths``. When a HUMAN approves a write at the gate, the
    resulting content's integrity hash is recorded here so the ADR-0036 tamper guard can excuse
    exactly that content. It is the operator's authorization expressed as a fact rather than as
    prose: before this, an operator could authorize a legitimate test amendment at the escalation
    gate and the deterministic guard would never see it, so the work deadlocked.

    ``coder_validation`` (F70, #75) is the third such shared map: ``run_tests`` records its
    engine-resolved output + the tree hash it was taken at, so a hand-raise escalation — which
    never reaches the ``test`` node — can still name what is blocking it. See ADR-0087.
    """
    from mosaera_policies.approval import ApprovalDecision, request_approval

    from mosaera_core.validation import resolve_plan, run_plan

    stuck_hint = _STUCK_HINT_WITH_DELETE if allow_delete else _STUCK_HINT

    # Content hashes already written to each path this run — used to refuse no-op /
    # duplicate writes (churn) before they reach the approval gate.
    _writes: dict[str, set[str]] = {}
    # Consecutive count of each identical run_tests FAILURE within this implement
    # session — a coder that re-runs the same failing suite without changing code is
    # not converging. Reset by any accepted write (a real edit → a legitimately new run).
    _test_fp_counts: dict[str, int] = {}
    # Owned HERE rather than passed in: `build_repo_tools` is called once per toolset per run, so a
    # local map is per-run and per-ACTOR for free — the coder and the Proctor each de-duplicate
    # their own view — with no new parameter threaded through `graph/build.py`, which is a hot file
    # two sessions have had to rebase around.
    _env_facts_seen: dict[str, str] = {}

    def _churn_reason(rel: str, content: str, existing: str | None) -> str | None:
        """Why writing ``content`` to ``rel`` makes no progress, or None."""
        if existing is not None and content == existing:
            return f"{rel} already contains exactly this content — the write changes nothing"
        if hashlib.sha256(content.encode()).hexdigest() in _writes.get(rel, set()):
            return f"you already wrote this exact content to {rel} earlier in this run"
        return None

    def _sanction(rel: str, decision: ApprovalDecision | None) -> None:
        """Record a HUMAN-approved write so the tamper guard can excuse exactly this content.

        Only ``actor == "human"`` may sanction. An autonomous auto-approve reaching here would let
        a run sanction its own edits to pre-existing tests and retire ADR-0036 in silence — the
        whole point is that a PERSON with standing said yes to THIS content.

        The hash is read back from DISK with the guard's own ``integrity_hash``, deliberately: a
        second implementation of "what content counts" could drift from the one that later judges
        it, and a sanction that no longer matches is a false park. Local import — testintegrity
        imports ``Workspace`` from this package.
        """
        if operator_sanctioned is None or decision is None:
            return
        if not decision.approved or decision.actor != "human":
            return
        from mosaera_core.testintegrity import integrity_hash

        operator_sanctioned[rel] = integrity_hash(workspace, rel)

    def _record_write(rel: str, content: str) -> None:
        _writes.setdefault(rel, set()).add(hashlib.sha256(content.encode()).hexdigest())
        # A real code change makes the next run_tests legitimately new, so the
        # repeated-failure guard must not throttle a genuinely progressing coder.
        _test_fp_counts.clear()

    _write_root = write_prefix.rstrip("/") if write_prefix else None

    def _scope_reason(rel: str, verb: str = "modify") -> str | None:
        """Why this toolset may not ``verb`` ``rel`` (separation of duties), or None.
        Protected paths are refused outright; ``write_prefix`` confines writes to one
        directory. The message steers the agent to escalate rather than route around."""
        # Git internals are never a legitimate agent write. This also keeps the delivery-exclusion
        # honest: the coder must not be able to edit .git/info/exclude to un-exclude the scratch
        # space (or any excluded path) and smuggle it into commit_all() (#59, ADR-0064).
        if rel == ".git" or rel.startswith(".git/"):
            return f"you may not {verb} anything under .git/ — git internals are off-limits"
        if rel in protected_paths:
            return (
                f"{rel} is a protected test file owned by the tester — you may not {verb} it. "
                "If the task genuinely requires changing it, reply 'SUMMARY: escalate — the task "
                "conflicts with a test: name it and the contradiction' so it can be re-authored."
            )
        if _write_root is not None and rel != _write_root and not rel.startswith(_write_root + "/"):
            return f"this agent may only write under {_write_root}/ — {rel} is out of scope"
        return None

    @tool
    def list_files(subdir: str = ".") -> str:
        """List files in the repository (relative paths), optionally under a subdirectory."""
        try:
            base = workspace.resolve(subdir)
        except PathEscapeError as exc:
            return f"ERROR: {exc}"
        prefix = base.relative_to(workspace.root).as_posix()
        if prefix in (".", ""):
            prefix = ""
        elif not prefix.endswith("/"):
            prefix += "/"
        entries = [p for p in workspace.file_listing() if p.startswith(prefix)]
        _emit_activity("list_files", subdir if subdir != "." else "", f"{len(entries)} entries")
        return "\n".join(entries) or "(no files)"

    @tool
    def read_file(path: str, start: int | None = None, limit: int | None = None) -> str:
        """Read a file from the repository. Provide a path relative to the repo root.

        Omit start/limit for the whole file. On a large file prefer a window: pass
        start (1-based line) and limit (line count) to get just those lines, numbered.
        A `search` hit is file:line, so it converts straight into a range.
        """
        try:
            target = workspace.resolve(path)
            text = target.read_text(encoding="utf-8", errors="replace")
        except PathEscapeError as exc:
            return f"ERROR: {exc}"
        except OSError as exc:
            return f"ERROR: cannot read {path}: {exc}"
        if start is None and limit is None:
            _emit_activity("file_read", path, f"{len(text.splitlines())} lines")
            if len(text) > _MAX_READ_CHARS:
                text = text[:_MAX_READ_CHARS] + (
                    f"\n... (truncated at {_MAX_READ_CHARS} chars — re-read with "
                    "start=/limit= for the part you need)"
                )
            return text
        return _windowed_read(path, text, start, limit)

    @tool
    def search(pattern: str) -> str:
        """Search file contents with a regular expression; returns file:line matches."""
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return f"ERROR: invalid regex: {exc}"
        _emit_activity("search", pattern)
        deadline = time.monotonic() + _SEARCH_DEADLINE_S
        hits: list[str] = []
        for rel in workspace.file_listing(limit=2000):
            if time.monotonic() > deadline:
                return "\n".join(hits) + "\n... (search timed out)"
            try:
                lines = (
                    (workspace.root / rel)
                    .read_text(encoding="utf-8", errors="replace")
                    .splitlines()
                )
            except OSError:
                continue
            for lineno, line in enumerate(lines, 1):
                if time.monotonic() > deadline:
                    return "\n".join(hits) + "\n... (search timed out)"
                # Cap the scanned substring: a catastrophic regex can't backtrack
                # over more than _MAX_SEARCH_LINE chars.
                if rx.search(line[:_MAX_SEARCH_LINE]):
                    hits.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                    if len(hits) >= _MAX_SEARCH_RESULTS:
                        return "\n".join(hits) + "\n... (result limit reached)"
        return "\n".join(hits) or "(no matches)"

    @tool
    def write_file(path: str, content: str) -> str:
        """Write a file inside the repository (full content). Requires human approval."""
        try:
            target = workspace.resolve(path)
        except PathEscapeError as exc:
            return f"ERROR: {exc}"
        rel = target.relative_to(workspace.root).as_posix()
        scope = _scope_reason(rel, "write")
        if scope is not None:
            return f"REFUSED: {path} — {scope}"
        reason = _disallowed_scratch(rel, scratch_enabled=enable_scratch)
        if reason is not None:
            return f"REFUSED: {path} — {reason}"
        # Refuse no-op / duplicate writes BEFORE the approval gate, so a write that
        # makes no progress never prompts the human (the guided write-approval loop).
        existing = (
            target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
        )
        churn = _churn_reason(rel, content, existing)
        if churn is not None:
            return f"REFUSED: {churn}. {stuck_hint}"
        if approval_gate:
            # An overwrite is shown as a DIFF against disk, not as the proposed file. Disk is
            # the last APPROVED state, so this is "what changes about what you already said
            # yes to" — the question a full-file rewrite otherwise hides (F27: a revert and a
            # fix look identical when the gate renders both as a wall of text). A NEW file has
            # nothing to diff against and keeps its original summary + payload exactly.
            summary = f"{actor} wants to write {path} ({len(content)} chars)"
            payload: dict[str, Any] = {"path": path, "content": _gate_content(content)}
            suffix, diff = _diff_against_disk(rel, existing, content)
            if diff:
                summary = f"{actor} wants to REWRITE {path}{suffix}"
                payload["diff"] = diff
            summary = _note_weakening(summary, payload, rel, existing, content)
            decision: ApprovalDecision = request_approval("write_file", summary, payload)
            if not decision.approved:
                return f"DENIED by human reviewer: {decision.feedback or 'no reason given'}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _sanction(rel, decision if approval_gate else None)
        _record_write(rel, content)
        # Distinct activity kind for scratch so an audit sees workbench usage vs. delivered writes.
        _emit_activity(
            "scratch_write" if under_scratch(rel) else "file_written",
            path,
            f"{len(content)} chars",
        )
        return f"Wrote {path} ({len(content)} chars)"

    @tool
    def edit_file(path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
        """Replace an exact snippet in an EXISTING file — the preferred way to change code.

        ``old_str`` must appear in the file exactly once (include enough surrounding
        context to make it unique) unless ``replace_all`` is set. Read the file first so
        the anchor matches character-for-character, whitespace included. Use write_file
        only to CREATE a new file or fully rewrite one. Requires human approval.
        """
        try:
            target = workspace.resolve(path)
        except PathEscapeError as exc:
            return f"ERROR: {exc}"
        scope = _scope_reason(target.relative_to(workspace.root).as_posix(), "edit")
        if scope is not None:
            return f"REFUSED: {path} — {scope}"
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return (
                f"ERROR: cannot edit {path}: file does not exist — "
                "use write_file to create a new file."
            )
        if not old_str:
            return "ERROR: old_str is empty. Use write_file to create or fully replace a file."
        count = content.count(old_str)
        if count == 0:
            return (
                f"ERROR: anchor not found in {path}. Read the file and copy the exact text "
                "to replace (whitespace and indentation included)."
            )
        if count > 1 and not replace_all:
            return (
                f"ERROR: anchor matches {count} times in {path}. Add surrounding context to "
                "make it unique, or pass replace_all=true to replace every occurrence."
            )
        updated = content.replace(old_str, new_str, -1 if replace_all else 1)
        if updated == content:
            return f"No change: new_str is identical to old_str in {path}."
        rel = target.relative_to(workspace.root).as_posix()
        churn = _churn_reason(rel, updated, None)
        if churn is not None:  # this edit reproduces content already written this run
            return f"REFUSED: {churn}. {stuck_hint}"
        n = count if replace_all else 1
        if approval_gate:
            # A REAL diff, same as write_file. `_edit_diff` emits every old line then every new
            # one, so a near-whole-file anchor blew the payload cap BEFORE any `+` line appeared —
            # the operator saw their whole file as deletions with no replacement, which reads like
            # a diff and is not one (F34, seen live). It stays as the `content` view; `diff` is
            # what DiffView renders.
            summary = f"{actor} wants to edit {path} ({n} replacement{'s' if n != 1 else ''})"
            payload = {"path": path, "content": _gate_content(_edit_diff(old_str, new_str))}
            suffix, diff = _diff_against_disk(rel, content, updated)
            if diff:
                summary += suffix
                payload["diff"] = diff
            summary = _note_weakening(summary, payload, rel, content, updated)
            decision = request_approval("edit_file", summary, payload)
            if not decision.approved:
                return f"DENIED by human reviewer: {decision.feedback or 'no reason given'}"
        target.write_text(updated, encoding="utf-8")
        _sanction(rel, decision if approval_gate else None)
        _record_write(rel, updated)
        kind = "scratch_write" if under_scratch(rel) else "file_written"
        _emit_activity(kind, path, f"{n} replacement{'s' if n != 1 else ''}")
        return f"Edited {path} ({n} replacement{'s' if n != 1 else ''}, {len(updated)} chars total)"

    @tool
    def run_tests() -> str:
        """Run the project's validation plan in the sandbox and return the output."""
        # Resolved at call time so files the coder just wrote (new tests,
        # new pages) upgrade the plan — the same honesty the delivery gate sees.
        plan = resolve_plan(workspace, test_cmd, install=install, install_timeout=install_timeout)
        outcome = run_plan(plan, sandbox, cwd=workspace.root)
        verdict = (
            "passed"
            if outcome.passed
            else ("failed" if outcome.passed is False else "no validator")
        )
        _emit_activity("running_validation", "", verdict)
        # ADR-0110 slice 1: on a FAILING suite, lead with what the environment measurably IS.
        # This is where the 2026-08-23 misdiagnosis actually formed — the producer read a traceback
        # here, concluded "what I'm editing isn't what's being executed — likely Python caching",
        # and escalated twice on it (run `20260823-220123-d624b9`). Facts only on the probe would
        # have missed this path entirely, since the belief never required calling the probe.
        facts = environment_facts(workspace, _env_facts_seen) if outcome.passed is False else ""
        body = f"{facts}[validation plan: {plan.project_type} — {plan.reason}]\n{outcome.output}"
        if coder_validation is not None:
            # Raw output, not `body` (the preamble is display chrome). Hash taken AFTER the run and
            # overwritten each time, so only the latest run — of the tree it actually saw — stands.
            coder_validation.update(output=outcome.output, tree_hash=workspace.evidence_hash())
        # Within-node token guard: a coder that re-runs the SAME failing suite without
        # an intervening code change is looping, not converging. After test_repeat_limit
        # identical failures, hand it the STOP directive so it yields instead of burning
        # its whole step budget re-running (the real cost). Keys on the FAILURE output
        # (normalized), so making DIFFERENT wrong edits doesn't evade it; a real write
        # clears the counter (_record_write).
        if outcome.passed is False and test_repeat_limit > 1:
            fp = fingerprint("test", outcome.output)
            n = _test_fp_counts.get(fp, 0) + 1
            _test_fp_counts[fp] = n
            if n >= test_repeat_limit:
                return (
                    f"{body}\n\nSTOP — run_tests has produced this SAME failure {n} times this "
                    "session with no code change resolving it. Do NOT run it again. Reply now "
                    "with 'SUMMARY: blocked — <the exact failure and the one thing you cannot "
                    "resolve>', or, if this needs a decision or a scope change (e.g. the task "
                    "conflicts with an existing test), 'SUMMARY: escalate — <what must be "
                    "decided>'."
                )
        return body

    @tool
    def delete_file(path: str) -> str:
        """Delete a single existing file from the repository. Human-gated in guided mode;
        in autonomous mode the runner auto-approves it (the delivery gate is the backstop,
        and deleting a pre-existing/protected test trips the integrity guard → parks).
        Use only when the task explicitly needs a file removed. Cannot delete directories
        or anything under .git."""
        try:
            target = workspace.resolve(path)
        except PathEscapeError as exc:
            return f"ERROR: {exc}"
        rel = target.relative_to(workspace.root).as_posix()
        if rel in ("", ".") or rel.split("/", 1)[0] == ".git":
            return (
                f"REFUSED: {path} — refusing to delete the workspace root or anything under .git."
            )
        scope = _scope_reason(rel, "delete")
        if scope is not None:
            return f"REFUSED: {path} — {scope}"
        if target.is_dir():
            return (
                f"ERROR: {path} is a directory — delete_file removes a single file, not a folder."
            )
        if not target.is_file():
            return f"ERROR: {path} does not exist — nothing to delete."
        if approval_gate:
            decision = request_approval(
                "delete_file", f"{actor} wants to DELETE {path}", {"path": path}
            )
            if not decision.approved:
                return f"DENIED by human reviewer: {decision.feedback or 'no reason given'}"
        target.unlink()
        _emit_activity("file_deleted", path, "removed")
        return f"Deleted {path}"

    tools = [list_files, read_file, search, edit_file, write_file, run_tests]
    if allow_delete:
        tools.append(delete_file)
    if enable_exec:
        tools.append(
            build_sandbox_exec(
                workspace, sandbox, fingerprint, exec_degradations, exec_usage, _env_facts_seen
            )
        )
    return tools
