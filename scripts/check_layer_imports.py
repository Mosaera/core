#!/usr/bin/env python3
"""Layer-boundary guard: fail if a package imports ACROSS the one-way dependency graph.

Enforces the dependency-direction rule (``CLAUDE.md`` → *No god-files* / *Dependency
direction is one-way*, ``coding-standards.md`` → *Maintainability and modularity*):

    apps/api · agents · connectors  →  core  →  policies
                                   ↘         ↘
                                     memory (a leaf — imports no sibling)

A lower layer must never import a higher one (the classic ``core → agents`` inversion);
invert via a protocol/injection instead. `memory` is the durable-state foundation and must
stay a dependency-free leaf; `policies` is the trust boundary and must stay low. This guard
makes those boundaries **un-writable** — a new upward import fails CI, so the class of
regression can't recur (it's the architecture-test rung of the prevent-repeats principle,
ADR-0041), complementing the god-file guard's size rung.

Like the god-file guard, KNOWN pre-existing crossings are GRANDFATHERED as a RATCHET: the
set may only SHRINK. They are the accepted DI debt (the engine still imports the agents via
``agents_bridge`` / the CLI wires the connector directly) being paid down by the AgentTeam
protocol work — do NOT add to it; invert the dependency instead.

Beyond the package graph, a second, FINER rule bans specific MODULE prefixes even when the
package as a whole is importable (``FORBIDDEN_MODULE_PREFIXES``). Its one job today: the
**untrusted project map** (ADR-0047) lives in the ``memory`` leaf but must never reach the
**gate** (``packages/policies``), so ``policies`` is forbidden the map's modules — making "the
map never reaches the gate" structural rather than merely agreed.

Run: ``python scripts/check_layer_imports.py`` (wired into ``make lint``, which CI runs).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Each source package → the sibling packages it must NOT import (its "higher" layers). Downward
# edges (e.g. core → policies/memory, agents/connectors/api → core) are allowed and omitted.
FORBIDDEN: dict[str, set[str]] = {
    # The leaf: imports NO sibling at all.
    "mosaera_memory": {
        "mosaera_core",
        "mosaera_policies",
        "mosaera_agents",
        "mosaera_connectors",
        "mosaera_api",
    },
    # The trust boundary: stays low — never reaches up into the engine or above.
    "mosaera_policies": {
        "mosaera_core",
        "mosaera_agents",
        "mosaera_connectors",
        "mosaera_api",
    },
    # The engine: may import policies/memory (down); never the model-facing/delivery/api layers.
    "mosaera_core": {"mosaera_agents", "mosaera_connectors", "mosaera_api"},
    # Delivery + model-facing: may import core/policies/memory; never the api app or each other.
    "mosaera_connectors": {"mosaera_agents", "mosaera_api"},
    "mosaera_agents": {"mosaera_connectors", "mosaera_api"},
}

# Finer-grained than the package graph above: specific MODULE prefixes a package must not import,
# even when the package as a whole is importable. This exists for one invariant (ADR-0047 §2): the
# **untrusted project map** lives in the ``memory`` leaf (which ``policies`` is otherwise allowed to
# import — secrets, etc.), but it must never reach the **gate**. If the map reached ``policies``,
# untrusted repo content would influence the decision to ship repo content. So the ban is at module
# granularity: the map's modules, plus the composed ``store`` facade (which mixes in ``MapMixin`` —
# importing it is a transitive path to the map). The **charter** modules are deliberately NOT here:
# posture (ADR-0046) is a governance input that may legitimately reach enforcement later.
#
# A match is exact or a dotted-prefix (``mosaera_memory.store`` also bans ``...store._x``). The
# ``from pkg import name`` form is name-qualified by ``_imported_modules`` to ``pkg.name``, so the
# ``MemoryStore`` entry catches ``from mosaera_memory import MemoryStore`` (and any alias of it) —
# the package __init__ re-exports the map-bearing facade at the top level, which is a static
# from-import path to the whole ``MapMixin``, distinct from the residual below.
# Honest residual: a BARE ``import mosaera_memory`` + attribute walk (``mosaera_memory.MemoryStore``
# reached via ``getattr``), and dynamic imports, can't be seen by static AST — the guard raises the
# cost of the wrong thing; it does not make it impossible. (A ``from mosaera_memory import *`` would
# also slip the prefix match, but ruff ``F403`` fails it in the same ``make lint``.)
FORBIDDEN_MODULE_PREFIXES: dict[str, tuple[str, ...]] = {
    "mosaera_policies": (
        "mosaera_memory.models_map",  # the untrusted-map ORM
        "mosaera_memory.store._map",  # the map read/write mixin
        "mosaera_memory.store",  # the composed store facade — a transitive path to the map
        "mosaera_memory.MemoryStore",  # the facade re-exported at the package top level
    ),
}

# Package import-name → its source directory under the repo root.
_PKG_DIR = {
    "mosaera_memory": "packages/memory",
    "mosaera_policies": "packages/policies",
    "mosaera_core": "packages/core",
    "mosaera_connectors": "packages/connectors",
    "mosaera_agents": "packages/agents",
}

# Pre-existing upward imports that predate the guard — the accepted DI debt (ratchet: may only
# shrink). Each is ``(repo-relative file, imported package)``. Invert via a protocol; never add.
GRANDFATHERED: set[tuple[str, str]] = {
    ("packages/core/mosaera_core/agents_bridge.py", "mosaera_agents"),
    ("packages/core/mosaera_core/cli.py", "mosaera_connectors"),
    ("packages/core/mosaera_core/tools/repo/clone.py", "mosaera_connectors"),
}

_EXCLUDE_SUBSTR = ("/__pycache__/", "/tests/", "/.venv/", "/migrations/", "/bench/cases/")


def _imported_packages(path: Path) -> set[str]:
    """The set of top-level ``mosaera_*`` packages ``path`` imports (via AST, so it sees both
    ``import mosaera_x`` and ``from mosaera_x.sub import y`` and ignores strings/comments).

    Caveat: static AST cannot see a DYNAMIC import (``importlib.import_module("mosaera_api")`` /
    ``__import__``). A determined cross-layer import can still be written that way; this guard,
    like any lint, raises the cost of the wrong thing rather than making it impossible."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".", 1)[0])
    return {m for m in found if m.startswith("mosaera_")}


def _imported_modules(path: Path) -> set[str]:
    """The set of full dotted ``mosaera_*`` module names ``path`` imports. Unlike
    ``_imported_packages`` this keeps the submodule path, so the map's specific modules can be
    forbidden while the rest of ``memory`` stays importable (see ``FORBIDDEN_MODULE_PREFIXES``):

    - ``import a.b.c``          → ``a.b.c``
    - ``from a.b.c import x``   → ``a.b.c`` AND ``a.b.c.x`` (``x`` may itself be a submodule)

    The second form matters: ``from mosaera_memory import store`` pulls in the ``...store`` facade
    (a transitive path to the map), and recording only ``node.module`` (``mosaera_memory``) would
    miss it. We add the name-qualified path too; it only ever matches a real forbidden module
    prefix, so a ``from pkg import SomeClass`` candidate (``pkg.SomeClass``) is harmless noise."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return {m for m in found if m.startswith("mosaera_")}


def module_offenders(pkg: str, imported_modules: set[str]) -> list[str]:
    """Pure check (unit-testable): the forbidden module prefixes ``pkg`` imported. A module matches
    a prefix when it equals it or is a dotted child (``p`` matches ``p`` and ``p.sub``, but not
    ``p_other``). Returns the offending imported module names, sorted."""
    prefixes = FORBIDDEN_MODULE_PREFIXES.get(pkg, ())
    if not prefixes:
        return []
    hits = {
        mod
        for mod in imported_modules
        for prefix in prefixes
        if mod == prefix or mod.startswith(prefix + ".")
    }
    return sorted(hits)


def main() -> int:
    offenders: list[tuple[str, str]] = []
    module_hits: list[tuple[str, str]] = []
    seen_grandfathered: set[tuple[str, str]] = set()
    for pkg, forbidden in FORBIDDEN.items():
        pkg_root = ROOT / _PKG_DIR[pkg]
        for path in sorted(pkg_root.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if any(s in f"/{rel}" for s in _EXCLUDE_SUBSTR):
                continue
            for target in _imported_packages(path) & forbidden:
                edge = (rel, target)
                if edge in GRANDFATHERED:
                    seen_grandfathered.add(edge)
                else:
                    offenders.append(edge)
            # Module-granular bans (the map must never reach the gate, ADR-0047 §2).
            for mod in module_offenders(pkg, _imported_modules(path)):
                module_hits.append((rel, mod))

    rc = 0
    if offenders:
        print(f"Layer-boundary guard FAILED: {len(offenders)} upward import(s).")
        # ASCII only: this prints to the console (cp1252 on Windows PowerShell, the documented
        # primary shell), and a non-ASCII char would crash the guard's OWN diagnostics on the
        # exact run where it fires. Matches check_file_sizes.py's ASCII-output convention.
        print("A lower layer imported a higher one - invert via a protocol/injection (CLAUDE.md):")
        for rel, target in sorted(offenders):
            print(f"  {rel}  ->  {target}")
        rc = 1

    if module_hits:
        print(f"\nForbidden-module guard FAILED: {len(module_hits)} banned module import(s).")
        print("The untrusted project map must never reach the gate (ADR-0047 section 2):")
        for rel, mod in sorted(module_hits):
            print(f"  {rel}  ->  {mod}")
        rc = 1

    stale = GRANDFATHERED - seen_grandfathered
    if stale:
        print("\nRatchet: these GRANDFATHERED crossings no longer exist - delete them from")
        print("GRANDFATHERED in scripts/check_layer_imports.py so the ratchet stays tight:")
        for rel, target in sorted(stale):
            print(f"  {rel}  ->  {target}")
        rc = 1

    if rc == 0:
        print("Layer-boundary guard OK: no new cross-layer imports.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
