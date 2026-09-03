"""The ``security`` dimension — gitleaks + semgrep in the sandbox (ADR-0047 §3).

Two things here are deliberate and worth reading before changing anything.

**1. This does not call ``Scanner.scan``, and that is not an oversight.**
``Scanner.scan`` ignores the sandbox exit code and hands stdout straight to
``parse``; every ``parse`` returns ``[]`` on unparseable input. So a missing binary
(``sh: gitleaks: not found``, empty stdout) would be indistinguishable from a clean
repo — exactly the false-green ADR-0047 §5 forbids in a **durable** artifact: a map
that says "no secrets" because gitleaks was absent is a lie that persists across every
future run.

So this dimension classifies the scanner's exit code with the ``_hosttools`` convention
(0 = ran/clean, 1 = ran/findings, anything else = no verdict) and requires a well-formed
report before trusting a zero-finding result as clean. As of ADR-0076 that classifier
(``run_one`` / ``emitted_report``) lives in ``tools.scan`` and is SHARED with the run
gate's ``scan_node`` — the two trust surfaces now agree on "did the scan actually run",
so the run gate no longer conflates missing-vs-clean either. This module keeps its own
``_observe`` (map-specific: severity + secret-free provenance).

**2. The map records the finding, never the secret.** gitleaks findings *are*
credential locations (ADR-0047's security implications say so explicitly). ``Finding``
carries ``rule``/``path``/``line`` and the rule *description* — gitleaks' ``Description``
and semgrep's ``extra.message``, never ``Secret``/``Match``/``extra.lines`` — so it is
already secret-free, and :func:`_observe` only ever reads those four fields. A test
pins this, because a later field addition to ``Finding`` would silently break it.

The scanners need a Docker sandbox (the scan image carries the binaries). No sandbox →
``unavailable``, never clean.
"""

from __future__ import annotations

from pathlib import Path

from mosaera_core.sandbox import SandboxWorker

# The scanner exit-code classifier now lives in tools.scan (ADR-0076) and is SHARED with
# the run gate's scan_node — recon re-exports it under the old private name so this module
# and its tests are unchanged.
from mosaera_core.tools.scan import Finding, build_scanners
from mosaera_core.tools.scan import run_one as _run_one

from . import _fingerprint, _fs
from .types import DimensionResult, Observation

DIMENSION = "security"

_MAX_REPORTED = 15


def _observe(finding: Finding) -> Observation:
    """One scanner finding → one provenanced observation.

    Reads ONLY rule/path/line — never a matched value. A gitleaks hit means "there is
    a credential at this location"; recording the credential itself would copy the
    secret into a durable, repo-derived artifact.
    """
    return Observation(
        text=f"{finding.scanner}: {finding.rule} at {finding.path}:{finding.line}",
        provenance=f"tool:{finding.scanner}",
        severity="critical",  # a located credential / SAST hit — the highest triage signal
    )


def recon_security(
    root: Path, sandbox: SandboxWorker | None, *, timeout: int | None = None
) -> DimensionResult:
    """Observe secret/SAST findings across the project.

    ``sandbox`` must be a Docker-backed worker (the scan image carries gitleaks +
    semgrep). ``None`` — the subprocess backend, or scanning disabled — is
    ``unavailable``: we did not look, so we cannot say the repo is clean.

    **Fingerprint scope — a deliberate divergence from ADR-0047 §4's example.** The
    ADR illustrates per-dimension keying with *"a lockfile edit must not invalidate
    the security scan"*. Taken literally that is unsafe: the scanners scan the **whole
    tree**, and lockfiles are a real place for credentials to live (a ``poetry.lock``
    or ``.npmrc`` index URL carries a token). If this dimension excluded lockfiles
    from its key, a secret committed to ``uv.lock`` would not re-trigger the scan and
    the map would go on reporting "clean" over a live credential.

    So security keys on **every** file. Over-invalidation costs a rescan;
    under-invalidation is a durable false-green over a leaked secret. That is the
    deny-by-default trade, and it is why §4's win is preserved by the *other*
    dimensions (deps/CI/quality key narrowly) rather than by this one.
    """
    fingerprint = _fingerprint.fingerprint_files(root, _fs.walk(root).files)

    if sandbox is None:
        return DimensionResult.could_not_run(
            DIMENSION, fingerprint, ["no scan sandbox — the scanners need the Docker backend"]
        )

    # build_scanners() enforces mosaera_policies.ALLOWED_SCANNERS (deny-by-default,
    # CODEOWNERS-gated). Recon adds no scanner of its own.
    scanners = build_scanners()
    if not scanners:
        return DimensionResult.could_not_run(DIMENSION, fingerprint, ["no scanners are allowed"])

    observations: list[Observation] = []
    unavailable: list[str] = []
    for scanner in scanners:
        findings, ran = _run_one(scanner, sandbox, timeout)
        if not ran:
            unavailable.append(scanner.name)
            continue
        if findings:
            observations.append(
                Observation(
                    text=f"{scanner.name} reports {len(findings)} finding(s)",
                    provenance=f"tool:{scanner.name}",
                    severity="high",
                )
            )
            observations += [_observe(f) for f in findings[:_MAX_REPORTED]]

    return DimensionResult.from_parts(DIMENSION, fingerprint, observations, unavailable)
