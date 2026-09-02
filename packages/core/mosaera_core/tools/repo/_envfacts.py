"""What the producer's environment ACTUALLY is — computed, not theorised (ADR-0110 slice 1).

A producer that cannot see its own environment narrates one. Measured twice, with the same
underlying blindness and two different invented causes:

- **F87** (`20260821-023819-4ad38a`) invented *"network issues installing dependencies"* while the
  code was correct and validation ran the same suite to 79 passed. Cost: 291,846 coder tokens.
- **2026-08-23** (`20260823-220123-d624b9`) invented *"likely Python caching or installation
  issues"* about an `UnboundLocalError` in code it had just written. Two escalations; the item
  never delivered.

F87's fix aimed the probe at the project's interpreter and measured **-62% coder tokens**. It closed
ONE way the environment could be misread. This module generalizes it, because the alternative —
a hand-written note per misdiagnosis — is what `_uninstalled_note` was, and ADR-0085 §1 froze that
pattern. The producer has already invented two causes; a per-symptom detector list has no end.

**Host-side by construction.** Every fact here is read from the workspace on the host: no container,
no timeout, no failure mode. A tool that fails while explaining a failure is worse than one
that says nothing, and this one runs precisely when something has already gone wrong.

**The rule that keeps it honest: never claim a mismatch that cannot be proven.** `pip install -e .`
runs INSIDE the container with `cwd=/work`, so an editable install records a container path.
Comparing that against the host-side workspace root would report a false *"your install points
elsewhere"* —
inventing a new external cause, which is the exact defect this module exists to remove. So the
recorded path is reported VERBATIM and no agreement is asserted. Silence beats a confident wrong
answer: the block is only worth anything if the producer can trust every line of it.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from mosaera_core.tools.repo._activity import emit_activity

# Enough changed files to ground a diagnosis without burying the failure output that follows.
_MAX_FILES = 12
# A `.pth` is one short line; anything larger is not the marker we understand, so report nothing
# rather than dump an unknown file into the producer's context.
_MAX_PTH_BYTES = 4_096


def _sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _stamp(mtime: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(mtime))


def _interpreter_line(workspace: Any) -> str:
    """Which interpreter the probe will use, and whether the project venv exists yet.

    The same `project_interpreter` the probe itself calls (F87's fix), stated out loud — so
    "my import fails" and "the venv is not built yet" stop being the same observation.
    """
    from mosaera_core.languages.python import project_interpreter

    venv = Path(workspace.root) / ".venv" / "bin" / "python"
    if venv.is_file():
        return f"interpreter : {project_interpreter(workspace)}"
    # The one inference kept from the retired `_uninstalled_note`, and kept because it is keyed on
    # TREE STATE (is there a venv?) and never on the failure text. That distinction is the whole of
    # ADR-0085 §1: a detector that reads the symptom goes stale as new symptoms appear; a fact about
    # the workspace does not. Worth stating because "the package isn't installed yet" and "my code
    # is broken" produce the same ImportError, and the producer cannot tell them apart unaided.
    return (
        f"interpreter : {project_interpreter(workspace)}\n"
        "              no project venv on disk yet — the install step has not run, so importing "
        "this project's\n              own package will fail here regardless of your code. "
        "`run_tests` installs it and runs the real suite."
    )


def _install_line(workspace: Any) -> str:
    """Where an editable install points, quoted exactly as recorded.

    Deliberately NOT compared against the workspace root — see the module docstring. The producer
    can read a `/work/...` path and draw its own conclusion; a wrong claim from this block would be
    worse than no claim at all.
    """
    site = list(Path(workspace.root).glob(".venv/lib/python*/site-packages"))
    if not site:
        return "install     : not installed into a project venv"
    pths = sorted(site[0].glob("__editable__*.pth"))
    if not pths:
        return "install     : no editable install marker (the package may be installed normally)"
    try:
        if pths[0].stat().st_size > _MAX_PTH_BYTES:
            return f"install     : editable, marker {pths[0].name} (unread — larger than expected)"
        recorded = pths[0].read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return "install     : editable, marker unreadable"
    target = recorded[0] if recorded else "(empty)"
    # "records" — not "points at", and not compared. The path is the container's.
    return f"install     : editable — {pths[0].name} records {target}"


def _changed_file_lines(workspace: Any) -> list[str]:
    """The bytes on disk for the files this run changed.

    THE load-bearing fact: it is what falsifies *"what I'm editing isn't what's executing"*. A
    producer holding that belief can compare the hash and timestamp here against the edit it just
    made, instead of reasoning about caches it cannot inspect.

    `diff_readonly` (never `diff_all`): the latter stages the whole tree as a side effect, and a
    block that explains a failure must not mutate the workspace it is describing.
    """
    from mosaera_core.quality import changed_python_files

    changed = changed_python_files(workspace.diff_readonly())
    if not changed:
        return []
    out = ["changed     : (path · size · sha256[:12] · mtime)"]
    for rel in changed[:_MAX_FILES]:
        p = Path(workspace.root) / rel
        try:
            st = p.stat()
        except OSError:
            out.append(f"              {rel} — not on disk")
            continue
        out.append(f"              {rel} · {st.st_size}B · {_sha12(p)} · {_stamp(st.st_mtime)}")
    if len(changed) > _MAX_FILES:
        out.append(f"              … and {len(changed) - _MAX_FILES} more")
    return out


def _pycache_line(workspace: Any) -> str:
    """Whether any compiled cache is older than its source.

    Named explicitly because *"Python caching"* is a cause the producer has actually invented. The
    answer is cheap to compute and settles it either way, rather than leaving a plausible story
    standing for want of a fact.
    """
    stale = 0
    fresh = 0
    for cache in Path(workspace.root).rglob("__pycache__"):
        if ".venv" in cache.parts:
            continue
        for pyc in cache.glob("*.pyc"):
            src = cache.parent / (pyc.name.split(".")[0] + ".py")
            try:
                if not src.is_file():
                    continue
                if pyc.stat().st_mtime < src.stat().st_mtime:
                    stale += 1
                else:
                    fresh += 1
            except OSError:
                continue
    if stale == 0 and fresh == 0:
        return "bytecode    : no __pycache__ in the source tree"
    if stale == 0:
        return f"bytecode    : {fresh} cached file(s), none older than its source"
    return f"bytecode    : {stale} of {stale + fresh} cached file(s) OLDER than the source"


def environment_facts(workspace: Any, seen: dict[str, str] | None = None) -> str:
    """The fact block, or ``""`` if anything at all goes wrong — or if it would only repeat itself.

    ``seen`` is a CALLER-OWNED map holding the digest of the last block shown, the same ownership
    `note_degradation` uses and for the same reason: a module global would let two concurrent runs
    in one process pollute each other. Pass ``None`` to disable de-duplication.

    Advisory like `emit_activity`: it is prepended to output the caller is already returning, so a
    raise here would turn a reported failure into a lost one.

    **Emits its own firing signal**, and that is not decoration. The first live A/B of this slice
    (2026-08-24, item #126) could not be attributed, because a tool's RETURN VALUE reaches no
    durable record — not the transcript, the report, the artifacts nor the events endpoint, none of
    which carry so much as `run_tests`' unconditional `[validation plan:` prefix. So "did the block
    fire?" had no obtainable answer, on that run or any future one, and the measurement ADR-0110
    requires was inference rather than observation.

    The same lesson `note_degradation` records one file over: a count with no denominator is not a
    measurement. One activity event makes every subsequent run answer the question.
    """
    try:
        lines = [_interpreter_line(workspace), _install_line(workspace)]
        changed = _changed_file_lines(workspace)
        lines.extend(changed)
        pycache = _pycache_line(workspace)
        lines.append(pycache)
        body = "\n".join(lines)
        # A SHORT shape, not the block: enough to see what the producer was handed and whether it
        # was worth handing over, without duplicating the payload into the stream.
        files = max(0, len(changed) - 1)  # the header line is not a file
        detail = f"{files} changed file(s)"
        state = "stale bytecode" if "OLDER" in pycache else "tree consistent"
        # Repeating UNCHANGED facts is noise, not evidence. Measured live 2026-08-24 (run
        # `20260824-015015-43a966`): a coder probing in circles failed 16 times and was handed 16
        # near-identical blocks — sixteen copies of the same paragraph in the context of an agent
        # already struggling to think straight. The block exists to end confusion; at that
        # frequency it plausibly adds to it. So it speaks when the facts MOVE and stays quiet when
        # they do not: the earlier block is still on the transcript and still accurate.
        #
        # The firing is recorded EITHER WAY, because "fired but suppressed" and "never fired" are
        # different facts and the A/B needs to tell them apart.
        digest = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:12]
        if seen is not None and seen.get("digest") == digest:
            emit_activity("environment_facts", detail, f"{state} · unchanged, not repeated")
            return ""
        if seen is not None:
            seen["digest"] = digest
        emit_activity("environment_facts", detail, state)
        return (
            "[environment — measured on disk, not inferred. If you are about to conclude that the "
            "code you edited is not the code that ran, check it against these facts first.]\n"
            f"{body}\n\n"
        )
    except Exception:
        return ""
