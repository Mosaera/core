"""Project recon: run the deterministic map dimensions in the background (#42, ADR-0047 §6).

Mirrors intake (``projects.py``): a daemon thread, so the trigger returns immediately and the UI
polls the durable map's per-dimension freshness. Recon reopens the project's existing clone, runs
the eight dimensions (security in the scan sandbox, tests in the main sandbox), and writes each
result to the map — never blocking the interactive path (§6), never authoring the charter (§1),
never a model call (§3; synthesis is MR3). The map itself is the authoritative poll source
(``list_map_dimensions``); ``_RUNNING`` is only a transient "in progress" overlay, lost on restart —
which is fine, recon is re-runnable (§7).
"""

from __future__ import annotations

import threading
from pathlib import Path

from mosaera_core.config import Settings
from mosaera_core.recon.orchestrate import recon_all
from mosaera_core.sandbox import SandboxUnavailable, SandboxWorker, create_sandbox
from mosaera_core.tools.repo import open_project_workspace
from mosaera_memory import MemoryStore

# Transient per-project recon state for the poll; the DURABLE truth is the map. Lost on restart.
_RUNNING: set[str] = set()
_LAST_ERROR: dict[str, str] = {}
_RECON_RUN_ID = "recon"  # synthetic run id for the read-only workspace open


def recon_state(project_id: str) -> dict[str, object]:
    """The transient recon overlay for the map-read endpoint: is a sweep in flight, and the last
    total-failure message (a clone that was never initialized, say). Per-dimension outcomes live in
    the durable map, not here."""
    return {"running": project_id in _RUNNING, "error": _LAST_ERROR.get(project_id)}


def _open_sandbox(settings: Settings, root: Path, image: str) -> SandboxWorker | None:
    """A sandbox for a recon dimension, or ``None`` when Docker is not reachable — a missing daemon
    makes that dimension report ``unavailable`` honestly rather than crashing the whole sweep."""
    try:
        return create_sandbox(
            settings.sandbox_backend,
            root,
            image=image,
            docker_bin=settings.docker_bin,
            default_timeout=settings.sandbox_timeout,
        )
    except SandboxUnavailable:
        return None


def run_recon(memory: MemoryStore, project_id: str) -> None:
    """Recon the project's existing clone and persist every dimension to the durable map."""
    _RUNNING.add(project_id)
    _LAST_ERROR.pop(project_id, None)
    try:
        settings = Settings.from_env()
        workspace = open_project_workspace(settings.projects_dir, project_id, _RECON_RUN_ID)
        test_sandbox = _open_sandbox(settings, workspace.root, settings.sandbox_image)
        scan_sandbox = (
            _open_sandbox(settings, workspace.root, settings.scan_image)
            if settings.sandbox_backend == "docker" and settings.scan_enabled
            else None
        )
        results = recon_all(workspace, test_sandbox=test_sandbox, scan_sandbox=scan_sandbox)
        for r in results:
            # A valid DimensionResult already satisfies the store's deny-by-default tri-state
            # invariants, so this upsert never raises; an empty fingerprint maps to NULL ⇒ stale.
            memory.upsert_map_dimension(
                project_id,
                r.dimension,
                status=r.status,
                fingerprint=r.fingerprint or None,
                observations=[
                    {"provenance": o.provenance, "text": o.text, "severity": o.severity}
                    for o in r.observations
                ],
                unavailable_reason="; ".join(r.unavailable),
            )
    except Exception as exc:
        _LAST_ERROR[project_id] = f"recon failed: {type(exc).__name__}: {exc}"[:300]
    finally:
        _RUNNING.discard(project_id)


def start_recon(memory: MemoryStore, project_id: str) -> None:
    """Kick off recon in a daemon thread; the trigger endpoint returns at once (§6)."""
    threading.Thread(target=run_recon, args=(memory, project_id), daemon=True).start()
