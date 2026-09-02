"""Run all eight recon dimensions over a workspace, isolating per-dimension failure (#42).

Each dimension is a pure recon function in :mod:`mosaera_core.recon`. Most take just the workspace
root; two need a sandbox, and they need DIFFERENT images — ``security`` runs gitleaks/semgrep in the
SCAN sandbox, ``tests`` runs the suite under coverage in the MAIN sandbox (the same split
``factory.py`` builds for a run as ``sandbox`` + ``scan_sandbox``). So the registry adapts each
dimension to one uniform ``(workspace, test_sandbox, scan_sandbox) -> DimensionResult`` shape. A
``None`` sandbox is honest, not fatal: that dimension reports ``unavailable`` ("we did not look")
rather than a false ``clean``.

The fan-out lives in ``core`` — not the store or the API daemon — so it stays deterministic and
unit-testable, and so ONE dimension crashing can never sink the other seven (ADR-0047 §5). No model
call, no persistence: the caller writes the returned results to the durable map.
"""

from __future__ import annotations

from collections.abc import Callable

from mosaera_core.recon import (
    DimensionResult,
    recon_ci,
    recon_cleanliness,
    recon_deps,
    recon_docs,
    recon_quality,
    recon_security,
    recon_structure,
    recon_tests,
)
from mosaera_core.sandbox import SandboxWorker
from mosaera_core.tools.repo.workspace import Workspace

# name → adapter to a uniform (workspace, test_sandbox, scan_sandbox) call. The keys MUST equal the
# store's ``MAP_DIMENSIONS`` (the upsert validates the name deny-by-default, so a drift surfaces at
# once). Each adapter picks the sandbox its dimension needs; the others ignore both.
_Adapter = Callable[[Workspace, SandboxWorker | None, SandboxWorker | None], DimensionResult]
_DIMENSIONS: dict[str, _Adapter] = {
    "ci": lambda ws, _ts, _ss: recon_ci(ws.root),
    "cleanliness": lambda ws, _ts, _ss: recon_cleanliness(ws.root),
    "deps": lambda ws, _ts, _ss: recon_deps(ws.root),
    "docs": lambda ws, _ts, _ss: recon_docs(ws.root),
    "quality": lambda ws, _ts, _ss: recon_quality(ws.root),
    "security": lambda ws, _ts, ss: recon_security(ws.root, ss),
    "structure": lambda ws, _ts, _ss: recon_structure(ws.root),
    "tests": lambda ws, ts, _ss: recon_tests(ws, ts),
}


def recon_all(
    workspace: Workspace,
    *,
    test_sandbox: SandboxWorker | None = None,
    scan_sandbox: SandboxWorker | None = None,
) -> list[DimensionResult]:
    """Run every recon dimension over ``workspace``, isolating per-dimension failure.

    ``test_sandbox`` runs the suite under coverage (tests dimension); ``scan_sandbox`` runs
    gitleaks/semgrep (security dimension). A dimension that raises is folded into an ``unavailable``
    result (empty fingerprint, so the store reads it stale and retries when inputs change) rather
    than crashing the sweep — a single tool on an untrusted clone cannot take down the whole map,
    and "did not run" is never rounded down to "clean" (§5). Deterministic and side-effect-free.
    """
    results: list[DimensionResult] = []
    for name, fn in _DIMENSIONS.items():
        try:
            results.append(fn(workspace, test_sandbox, scan_sandbox))
        except Exception as exc:  # an untrusted-repo tool can fail any number of ways
            reason = f"{type(exc).__name__}: {exc}"[:200]
            results.append(DimensionResult.could_not_run(name, fingerprint="", reasons=[reason]))
    return results
