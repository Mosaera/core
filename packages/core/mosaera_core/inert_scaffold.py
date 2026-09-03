"""Engine-authored oracle for a certified non-behavioural change (#118, Approach B).

**The difference from Approach A, in one line.** A *skips* the authoring node and leans on the
gate's existing `standing_suite` leg; B keeps the node and replaces the Proctor's MODEL CALL with a
deterministic one the ENGINE writes. A is cheaper. B verifies the actual claim.

**The claim a non-behavioural change makes is falsifiable, and nobody was checking it.** "This only
edits a comment" asserts that the module's observable surface is unchanged. That is not a matter of
judgement — it is a snapshot taken from the pre-change tree and compared after. So the engine can
author it, exactly as `scaffold_if_refactor` authors the differential golden-master for a detected
refactor (ADR-0066/0072). Same pattern, adjacent trigger.

**Why this is not the ADR-0062 auto-loosen.** That mechanism REWROTE an assertion so more things
passed. This ADDS an assertion that did not exist, and it can only ever refuse more. Directionally
opposite: the acceptance class narrows, and the run that would have shipped uncheckedon A's lane is
the run this catches.

**Arming reads the TRUSTED TASK ONLY.** `scaffold_if_refactor` records a live failure (MCB-11) where
the detector was armed by the PM's lossy paraphrase rather than the brief, planting an unmeetable
bar on a feature task. The classifier this defers to has the same rule, and the plan is consulted
only for a scope that is re-measured after the fact.

**Best-effort by construction.** Any fault returns ``[]`` and the Proctor authors as usual, so a
scaffold bug can never break a run — the same contract the refactor scaffold holds itself to.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

_HEADER = '''"""ENGINE-AUTHORED (#118 Approach B) — do not edit by hand.

The item was deterministically certified as a NON-BEHAVIOURAL change to {module}. That claim is
falsifiable, so it is written down as a test rather than trusted: the module must still import, and
its public surface must be exactly what it was before the change. A comment edit passes this; an
edit that quietly renames, adds or removes a public name does not, and the run refuses it.

Snapshot taken from the pristine pre-change tree by `inert_scaffold.py`.
"""

import importlib


def test_the_module_still_imports() -> None:
    """The cheapest possible falsification: a comment edit that breaks the parse."""
    importlib.import_module({module!r})


def test_the_public_surface_is_unchanged() -> None:
    """A non-behavioural change may not add, remove or rename a public name."""
    mod = importlib.import_module({module!r})
    actual = sorted(n for n in dir(mod) if not n.startswith("_"))
    assert actual == {expected!r}, (
        "the public surface changed, so this was not a non-behavioural change"
    )
'''


def _module_name(root: Path, rel: str) -> str:
    """Dotted module path for a repo-relative ``.py`` file, or ``""`` when it is not PROVABLY
    importable from the repo root.

    RED-TEAM B-1, closed here. The first version derived ``src/report.py`` -> ``src.report`` from
    the path alone. That only imports if the repo happens to be laid out that way; under a
    src-layout (``src/`` is a source ROOT, not a package) the oracle fails on import for a reason
    has nothing to do with the change, and EVERY reduced-lane run parks. Authoring cannot verify
    importability by importing — it runs before the coder and outside the sandbox — so it verifies
    it STRUCTURALLY instead and declines when it cannot.

    Two shapes are provable and nothing else is accepted:

    - a file at the repo ROOT (``ledger.py`` -> ``ledger``): importable with the root on the path,
      which is how the engine runs the suite;
    - a file whose every parent directory is a real PACKAGE (each carries ``__init__.py``), so the
      dotted path is the actual module path.

    A src-layout, a namespace package, or anything requiring an installed distribution returns "".
    Deny-by-default: declining costs a Proctor authoring pass, guessing costs the whole run.
    """
    if not rel.endswith(".py") or rel.endswith("__init__.py"):
        return ""
    parts = rel[:-3].split("/")
    if not all(p.isidentifier() for p in parts):
        return ""
    if len(parts) == 1:
        return parts[0]
    # Every parent must be a package, checked on disk rather than assumed from the path.
    for depth in range(1, len(parts)):
        if not (root / Path(*parts[:depth]) / "__init__.py").is_file():
            return ""
    return ".".join(parts)


def _public_names(source: str) -> list[str] | None:
    """Module-level public names, read STATICALLY. ``None`` when the file does not parse.

    Deliberately AST, never import: authoring runs before the coder, and importing arbitrary repo
    code to take a snapshot would execute it outside the sandbox.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and not t.id.startswith("_"):
                    names.add(t.id)
        elif isinstance(node, ast.ImportFrom | ast.Import):
            for a in node.names:
                bound = a.asname or a.name.split(".")[0]
                if not bound.startswith("_"):
                    names.add(bound)
    return sorted(names)


def scaffold_if_inert(
    workspace: Any, *, enabled: bool, certified_paths: tuple[str, ...]
) -> list[str]:
    """Author the API-snapshot oracle for a certified non-behavioural change; ``[]`` otherwise.

    ``certified_paths`` comes from `task_scale.classify` and is already intersected with the real
    repo, so this never invents a target. Returns the repo-relative paths it wrote, for the caller
    to fold into ``authored_tests`` — which is what makes them protected from the coder,
    tamper-guarded, and visible to the normal oracle path.
    """
    if not enabled or len(certified_paths) != 1:
        return []
    rel = certified_paths[0]
    module = _module_name(Path(workspace.root), rel)
    if not module:
        return []  # docs, config, a package __init__ — nothing importable to pin
    try:
        source = (Path(workspace.root) / rel).read_text(encoding="utf-8", errors="replace")
        expected = _public_names(source)
        if expected is None:
            return []  # already unparseable — a snapshot would pin the breakage
        out = Path(workspace.root) / "tests" / f"test_inert_{module.replace('.', '_')}.py"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_HEADER.format(module=module, expected=expected), encoding="utf-8")
        return [str(out.relative_to(Path(workspace.root)))]
    except OSError:
        return []
