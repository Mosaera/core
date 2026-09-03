#!/usr/bin/env python3
"""RunState key guard: fail if production code reads a key ``RunState`` does not declare.

LangGraph silently DROPS any key a ``TypedDict`` channel does not declare (ADR-0026). So a read
of an undeclared key is not a crash and not a warning — it is a permanent empty value, and the
code around it goes on behaving as though the answer were legitimately "nothing". That is the
quietest bug shape this repo produces, and it has now been measured four times:

- **F66** — ``state["acceptance"]`` was never a RunState key. The amendment offer went out with an
  EMPTY criterion, so the operator was asked to authorise changing an acceptance test without
  being shown what the item wanted. A test fixture had INVENTED the key, so the suite was green
  the whole time.
- The ``state["workspace_root"]`` near-miss, caught by hand hours later in the same file.
- **2026-08-07 audit** — ``run_diagnosis`` read ``terminal_vouch`` (a key that exists only on the
  BENCH harness dataclass) and a top-level ``unsatisfied_claims`` (it lives under
  ``gate_decision``), so every live run recorded an empty vouch — in the module whose entire
  stated purpose is that a live run's outcome must mean what a bench run's outcome means.

Every one of those is statically detectable, which is what this guard does. It is the
architecture-test rung of the prevent-repeats principle (ADR-0041), alongside the god-file and
layer-boundary ratchets.

**Deliberately narrow, so a hit is always real.** Only literal string subscripts/`.get()` on
identifiers named ``state`` / ``final`` are considered — the two names the engine and the
disposition/bench readers actually use. A computed key, a loop variable or an aliased mapping is
not flagged: this guard is worth having only if a failure means "you have a bug", never "go add an
exclusion".

**Tests are excluded on purpose, and that is not a loophole — it is the point.** F66's fixture
invented the key; a guard that also scanned tests would have been satisfied by that invention.
Production is the only place the declaration has to hold.

**Unreadable input FAILS.** A file that will not parse cannot be shown to be clean, and
"could not look" must never be spelled "passed" — the vacancy shape recorded against
``bump_version.py --verify-record`` and ``check_layer_imports``. ``check_doc_links.py`` already
does this correctly and is the model here.

Run: ``python scripts/check_state_keys.py`` (wired into ``make lint``, which CI runs).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DEF = ROOT / "packages" / "core" / "mosaera_core" / "graph" / "state.py"
SCAN_ROOTS = ("packages", "apps")
# The identifiers whose string keys are checked. `state` is the graph-node parameter; `final` is
# the post-run mapping the disposition/escalate arms and `run_diagnosis` read.
TRACKED_NAMES = {"state", "final"}


def declared_keys() -> set[str]:
    """Every key declared on the ``RunState`` TypedDict, including inherited bases in this file."""
    tree = ast.parse(STATE_DEF.read_text(encoding="utf-8"), filename=str(STATE_DEF))
    classes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    if "RunState" not in classes:
        raise SystemExit(f"check_state_keys: no RunState class in {STATE_DEF} — guard is broken.")

    keys: set[str] = set()
    seen: set[str] = set()

    def collect(name: str) -> None:
        if name in seen or name not in classes:
            return
        seen.add(name)
        node = classes[name]
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                keys.add(stmt.target.id)
        for base in node.bases:
            if isinstance(base, ast.Name):
                collect(base.id)

    collect("RunState")
    return keys


def _key_of(node: ast.AST) -> str | None:
    """The literal string key this node reads off `state`/`final`, or None if it is not one."""
    # state["x"] / final["x"]
    if isinstance(node, ast.Subscript):
        value, sl = node.value, node.slice
        if isinstance(value, ast.Name) and value.id in TRACKED_NAMES:
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                return sl.value
        return None
    # state.get("x") / final.get("x")
    if isinstance(node, ast.Call):
        fn = node.func
        if (
            isinstance(fn, ast.Attribute)
            and fn.attr == "get"
            and isinstance(fn.value, ast.Name)
            and fn.value.id in TRACKED_NAMES
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            return str(node.args[0].value)
    return None


def _production_files() -> list[Path]:
    out: list[Path] = []
    for root in SCAN_ROOTS:
        for path in sorted((ROOT / root).rglob("*.py")):
            parts = path.parts
            if "tests" in parts or "test" in parts or path.name.startswith("test_"):
                continue
            if "migrations" in parts or "__pycache__" in parts:
                continue
            out.append(path)
    return out


def offenders(declared: set[str]) -> list[str]:
    """Every undeclared read, plus every file that could not be read — never a silent skip."""
    fails: list[str] = []
    for path in _production_files():
        rel = path.relative_to(ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            # "Could not look" is NOT "clean" — the whole reason this guard exists.
            fails.append(f"{rel}: could not be parsed, so it cannot be shown clean ({exc})")
            continue
        for node in ast.walk(tree):
            key = _key_of(node)
            if key is not None and key not in declared:
                fails.append(
                    f"{rel}:{getattr(node, 'lineno', '?')}: reads undeclared RunState key "
                    f"{key!r} — LangGraph drops it (ADR-0026), so this is permanently empty. "
                    f"Declare it in graph/state.py, or read it where it actually lives."
                )
    return fails


def main() -> int:
    declared = declared_keys()
    fails = offenders(declared)
    if fails:
        print("RunState key guard FAILED:")
        for f in fails:
            print(f"    {f}")
        return 1
    print(f"RunState key guard OK: {len(declared)} declared keys, no undeclared reads.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
