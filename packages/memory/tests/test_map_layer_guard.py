"""The structural invariant of #40 / ADR-0047 §2: the untrusted project map must never reach the
gate. ``scripts/check_layer_imports.py`` makes it un-writable — a ``mosaera_policies`` file that
imports the map fails CI. These tests PROVE it fails (and that the charter / the scoping consumers
are still allowed), so the guard can't silently regress into a no-op.

The guard is a repo-root script, not an installed package, so we load it by file path."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_GUARD = _ROOT / "scripts" / "check_layer_imports.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_check_layer_imports_under_test", _GUARD)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def test_policies_importing_the_map_mixin_is_caught() -> None:
    # The map read/write mixin — the direct path to map data.
    assert guard.module_offenders("mosaera_policies", {"mosaera_memory.store._map"}) == [
        "mosaera_memory.store._map"
    ]


def test_policies_importing_the_map_orm_is_caught() -> None:
    assert guard.module_offenders("mosaera_policies", {"mosaera_memory.models_map"}) == [
        "mosaera_memory.models_map"
    ]


def test_policies_importing_the_store_facade_is_caught() -> None:
    # The composed facade mixes in MapMixin — a transitive path to the map, so it is banned too.
    assert guard.module_offenders("mosaera_policies", {"mosaera_memory.store"}) == [
        "mosaera_memory.store"
    ]


def test_policies_importing_the_top_level_memorystore_reexport_is_caught() -> None:
    # `from mosaera_memory import MemoryStore` — the package __init__ re-exports the map-bearing
    # facade at the top level. _imported_modules name-qualifies it to `mosaera_memory.MemoryStore`,
    # which must be banned (red-team G1 — this static from-import bypassed the earlier ban).
    assert guard.module_offenders("mosaera_policies", {"mosaera_memory.MemoryStore"}) == [
        "mosaera_memory.MemoryStore"
    ]


def test_from_memory_import_memorystore_is_caught_e2e(tmp_path: Path) -> None:
    f = tmp_path / "reexport.py"
    f.write_text("from mosaera_memory import MemoryStore as S\n", encoding="utf-8")
    # asname is ignored (name-qualified on alias.name), so the alias form is caught too.
    assert guard.module_offenders("mosaera_policies", guard._imported_modules(f)) == [
        "mosaera_memory.MemoryStore"
    ]


def test_a_child_module_of_a_banned_prefix_is_caught() -> None:
    # Dotted-prefix matching: store._anything is under the banned `mosaera_memory.store`.
    assert guard.module_offenders("mosaera_policies", {"mosaera_memory.store._runs"}) == [
        "mosaera_memory.store._runs"
    ]


def test_policies_importing_the_charter_is_allowed() -> None:
    # Charter (trusted, carries posture) is deliberately NOT banned — posture may reach enforcement.
    assert guard.module_offenders("mosaera_policies", {"mosaera_memory.models_charter"}) == []


def test_a_similarly_named_package_is_not_a_false_match() -> None:
    # Prefix match is dotted-boundary aware: `mosaera_memory.store_helpers` is NOT under `.store`.
    assert guard.module_offenders("mosaera_policies", {"mosaera_memory.store_helpers"}) == []


def test_core_may_read_the_map() -> None:
    # The map informs SCOPING — core/agents are its intended consumers; only policies is banned.
    assert guard.module_offenders("mosaera_core", {"mosaera_memory.store._map"}) == []
    assert guard.module_offenders("mosaera_agents", {"mosaera_memory.models_map"}) == []


def test_shipped_tree_passes_the_guard() -> None:
    # The real repo must be clean: no policies file imports the map today, and no new cross-layer
    # import slipped in. `make lint` runs this same check; the test locks it in offline too.
    assert guard.main() == 0


@pytest.mark.parametrize(
    "banned",
    [
        "mosaera_memory.models_map",
        "mosaera_memory.store._map",
        "mosaera_memory.store",
        "mosaera_memory.MemoryStore",
    ],
)
def test_every_configured_prefix_is_actually_enforced(banned: str) -> None:
    # Guards the config itself: each entry in FORBIDDEN_MODULE_PREFIXES[policies] must trip.
    assert guard.module_offenders("mosaera_policies", {banned}) == [banned]


def test_from_package_import_submodule_evasion_is_caught(tmp_path: Path) -> None:
    # `from mosaera_memory import store` pulls in the facade (a transitive path to the map) but its
    # AST `node.module` is only `mosaera_memory`. The extractor must also record `...store` so the
    # ban still fires — otherwise this is a trivial bypass.
    f = tmp_path / "evasive.py"
    f.write_text("from mosaera_memory import store\n", encoding="utf-8")
    mods = guard._imported_modules(f)
    assert "mosaera_memory.store" in mods
    assert guard.module_offenders("mosaera_policies", mods) == ["mosaera_memory.store"]


def test_plain_import_dotted_form_is_caught(tmp_path: Path) -> None:
    f = tmp_path / "dotted.py"
    f.write_text("import mosaera_memory.store._map as m\n", encoding="utf-8")
    assert guard.module_offenders("mosaera_policies", guard._imported_modules(f)) == [
        "mosaera_memory.store._map"
    ]
