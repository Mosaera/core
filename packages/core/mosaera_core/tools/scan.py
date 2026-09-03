"""Security scanners that run over a cloned workspace inside the sandbox.

Interface-first (like the sandbox): ``Scanner`` is the contract and
``GitleaksScanner`` (secrets) is the first concrete implementation. Semgrep
(SAST) and Trivy (deps/IaC) are same-shape follow-ups — each supplies a command
and a parser. Findings feed the Reviewer and the delivery report; the set of
scanners permitted to run is governed by ``mosaera_policies.ALLOWED_SCANNERS``.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from mosaera_policies import scanner_allowed

from mosaera_core.sandbox import SandboxWorker

# Where the workspace is mounted inside the sandbox container.
_WORK = "/work"
# gitleaks writes its JSON report here (the container's writable tmpfs) and we
# cat it to stdout. Writing to `/dev/stdout` directly is silently dropped when
# the container runs as root (fd-owner quirk), so a real file is robust for
# every container user.
_GITLEAKS_REPORT = "/tmp/gitleaks-report.json"  # noqa: S108 — container tmpfs path


# The normalized severity vocabulary (low → critical). Carried as DATA only — the
# delivery gate does NOT tier on it (a nonzero finding of any severity still parks via
# `security_findings`); it feeds the reviewer prompt, the report, and a future
# posture-gated tiering. Kept as bare strings, not an enum, to match `Finding`'s frozen
# shape and to avoid a cross-package import from `recon` (dependency direction is
# recon → tools, never the reverse).
Severity = Literal["low", "medium", "high", "critical"]

# scan_node's execution verdict for a whole run. Distinct from the FINDINGS: "unavailable"
# means we could not obtain a verdict (a missing/crashed scanner, no scan sandbox), which
# the gate must never round down to "clean" (deny-by-default). Mirrors recon's tri-state
# DimensionResult for the durable map — see run_scan / the recon docstring.
SecurityStatus = Literal["clean", "findings", "unavailable"]


def _normalize_severity(raw: str) -> Severity:
    """Semgrep's ERROR/WARNING/INFO vocabulary → the normalized tier.

    Unknown or missing severity is "medium", never rounded DOWN — deny-by-default over a
    signal we did not positively read (a semgrep result with no `extra.severity`, or a
    future rule vocabulary we don't recognize, must not silently become "low").
    """
    up = raw.strip().upper()
    if up == "ERROR":
        return "high"
    if up == "INFO":
        return "low"
    # WARNING and any unknown/missing vocabulary → deny-by-default "medium".
    return "medium"


def _normalize_confidence(value: Any) -> str:
    """Semgrep's `metadata.confidence` (HIGH/MEDIUM/LOW) → lowercase, else "" (unknown).

    Deliberately NOT deny-by-default like `_normalize_severity`: severity rounds an unknown
    UP because under-reporting how bad a finding is would be unsafe, but confidence has no
    such asymmetry and nothing tiers on it. Inventing a tier for a value semgrep never
    declared would be a fabricated signal — absent-means-unknown is the honest encoding.
    """
    low = _first_str(value).lower()
    return low if low in ("high", "medium", "low") else ""


def _first_str(value: Any) -> str:
    """A metadata field semgrep emits as EITHER a bare string or a list of them → one string.

    The rule schema permits both spellings for `subcategory` (and several other metadata
    keys), so a parser that assumes one shape silently drops the other.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def _normalize_cwe(value: Any) -> tuple[str, ...]:
    """`metadata.cwe` (a string or a list of them) → a tuple, keeping `Finding` hashable.

    Values are carried VERBATIM ("CWE-89: Improper Neutralization of ..."), not parsed down
    to an id: the id and its title are the vocabulary the rule author chose, and re-deriving
    a shortened form here would be this module inventing a taxonomy rather than carrying one.
    """
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, list):
        return tuple(v.strip() for v in value if isinstance(v, str) and v.strip())
    return ()


@dataclass(frozen=True)
class Finding:
    scanner: str
    rule: str
    path: str
    line: int
    message: str
    # Normalized triage tier (see Severity). Trailing + defaulted so existing positional
    # constructions stay valid; DATA only — no gate tiering (MR-1). Default "medium" is the
    # deny-by-default rounding for a finding whose scanner declares no severity.
    severity: str = "medium"
    # Triage metadata the scanner itself declares, carried on the SAME terms as severity:
    # trailing + defaulted, and DATA ONLY. The delivery gate keys on the finding COUNT alone
    # (`gate.evaluate_gate(findings_count=...)`) and `mosaera_policies` never imports this
    # dataclass — tiering the gate on any of these would LOOSEN it (a finding that parks today
    # would ship), the non-monotonic trust-boundary change ADR-0076 explicitly rejected.
    # These also stay out of `format_findings`, so the reviewer prompt is unchanged: the fields
    # are here to be measured before anything acts on them.
    #
    # "" / () means the scanner declared nothing — NOT a default tier. See _normalize_confidence.
    confidence: str = ""
    # semgrep's own rule vocabulary: "vuln" | "audit" | "guardrail". The one triage taxonomy
    # here that is derived from the ruleset rather than authored by us.
    subcategory: str = ""
    cwe: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanner": self.scanner,
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "severity": self.severity,
            "confidence": self.confidence,
            "subcategory": self.subcategory,
            # list, not tuple: this dict is JSON-serialized into the LangGraph checkpoint.
            "cwe": list(self.cwe),
        }


class Scanner(ABC):
    name: str

    @abstractmethod
    def command(self) -> list[str]: ...

    @abstractmethod
    def parse(self, stdout: str) -> list[Finding]: ...

    def scan(self, sandbox: SandboxWorker, timeout: int | None = None) -> list[Finding]:
        result = sandbox.run(self.command(), timeout=timeout)
        return self.parse(result.stdout)

    def reported_completely(self, stdout: str) -> bool:
        """Positive evidence THIS scanner produced a COMPLETE report of its own shape — not
        merely valid JSON, and not a run that reported it could not process some target.

        This is the "may a zero-finding result be trusted as CLEAN" contract (ADR-0076
        red-team A): a scan that ran but skipped/failed on a file is *not* clean-by-omission.
        The base is generic JSON-well-formedness; a scanner whose report carries a scan-error
        channel (semgrep's ``errors``) or a fixed top-level shape overrides this."""
        return emitted_report(stdout)


def _json_array(stdout: str) -> list[dict[str, Any]]:
    """Parse a JSON array from scanner stdout, tolerating leading log noise."""
    start = stdout.find("[")
    if start == -1:
        return []
    try:
        data = json.loads(stdout[start:])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


class GitleaksScanner(Scanner):
    name = "gitleaks"

    def command(self) -> list[str]:
        # Write the report to a tmpfs file, then cat it to stdout — see
        # _GITLEAKS_REPORT. gitleaks' own logs go to stderr; redirect its stdout
        # there too so stdout carries only the JSON the parser reads.
        scan = (
            f"gitleaks dir {_WORK} --report-format json --report-path {_GITLEAKS_REPORT} "
            f"--exit-code 0 --no-banner >&2; cat {_GITLEAKS_REPORT}"
        )
        return ["sh", "-c", scan]

    def reported_completely(self, stdout: str) -> bool:
        # gitleaks emits a top-level JSON ARRAY (`[]` when clean); scan errors go to stderr
        # + a non-zero exit (already classified by run_one). A body that is NOT a JSON array
        # (an object, an error dump, empty) is not its report → no verdict, never clean.
        s = stdout.strip()
        start = s.find("[")
        if start == -1:
            return False
        try:
            return isinstance(json.loads(s[start:]), list)
        except (json.JSONDecodeError, ValueError):
            return False

    def parse(self, stdout: str) -> list[Finding]:
        findings: list[Finding] = []
        for item in _json_array(stdout):
            path = str(item.get("File", "")).removeprefix(f"{_WORK}/")
            findings.append(
                Finding(
                    scanner=self.name,
                    rule=str(item.get("RuleID", "")),
                    path=path,
                    line=int(item.get("StartLine", 0) or 0),
                    message=str(item.get("Description", "")),
                    # A located secret is inherently critical — gitleaks emits no per-finding
                    # severity, so the scanner (not the dataclass default) fixes it here.
                    severity="critical",
                )
            )
        return findings


class SemgrepScanner(Scanner):
    """SAST over the workspace. Runs with BUNDLED LOCAL rules only — the scan
    sandbox is ``--network none``, so registry configs (``p/...`` / ``auto``)
    can't fetch; metrics + version-check are disabled to avoid phone-home."""

    name = "semgrep"
    _RULES = "/etc/semgrep-rules"  # vendored ruleset baked into the scan image

    def command(self) -> list[str]:
        return [
            "semgrep",
            "scan",
            "--json",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
            # Disable semgrep's default 1MB per-file skip (--max-target-bytes 1000000): a
            # SILENTLY skipped large file leaves `errors:[]` and reads as CLEAN (ADR-0076
            # red-team round 2 — a vuln planted in a >1MB file would false-ship). 0 = no limit;
            # an over-large file that then times out is killed by the sandbox → unavailable →
            # park (fails safe). The residual skip classes (too_many_matches, etc.) are the
            # coverage-oracle successor's mandate, not another skip-reason blocklist.
            "--max-target-bytes",
            "0",
            "--config",
            self._RULES,
            _WORK,
        ]

    @staticmethod
    def _load_object(stdout: str) -> dict[str, Any] | None:
        start = stdout.find("{")
        if start == -1:
            return None
        try:
            data = json.loads(stdout[start:])
        except (json.JSONDecodeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def reported_completely(self, stdout: str) -> bool:
        # semgrep emits an OBJECT; a COMPLETE run has a `results` key AND an EMPTY `errors`
        # array. A non-empty `errors` (a file it could not parse, a timeout) means it did NOT
        # scan everything — no verdict (deny-by-default), even at exit 0. This is the
        # red-team-A false-green: "ran, but not to completion" must never read as clean.
        # NOTE (red-team round 2, STOP-rule): the `errors` channel catches parse errors but
        # NOT a silently-skipped file (size / too_many_matches). The size vector is closed at
        # the source by `--max-target-bytes 0`; the general case is the coverage-oracle
        # successor's job — do NOT extend this into a third skip-reason blocklist here.
        data = self._load_object(stdout)
        if data is None or "results" not in data:
            return False
        errors = data.get("errors", [])
        # A non-list `errors` (null / {} / a string) is malformed semgrep output → fail
        # closed (incomplete), never trusted as "no errors".
        return isinstance(errors, list) and not errors

    def parse(self, stdout: str) -> list[Finding]:
        # Semgrep emits an OBJECT {"results": [...]}, not a top-level array.
        data = self._load_object(stdout)
        if data is None:
            return []
        findings: list[Finding] = []
        for item in data.get("results", []):
            path = str(item.get("path", "")).removeprefix(f"{_WORK}/")
            # semgrep namespaces a local rule id with its config path
            # (/etc/semgrep-rules → "etc.semgrep-rules.<id>"); strip that noise.
            rule = str(item.get("check_id", "")).removeprefix("etc.semgrep-rules.")
            extra = item.get("extra")
            extra = extra if isinstance(extra, dict) else {}
            # Same defensive shape as `extra` above: a malformed `metadata` (null, a list, a
            # string) must degrade to "declared nothing", never raise mid-scan.
            meta = extra.get("metadata")
            meta = meta if isinstance(meta, dict) else {}
            findings.append(
                Finding(
                    scanner=self.name,
                    rule=rule,
                    path=path,
                    line=int((item.get("start") or {}).get("line", 0) or 0),
                    message=str(extra.get("message", "")),
                    # semgrep declares ERROR/WARNING/INFO per rule; normalize it (a result
                    # with no severity → "medium", never rounded down).
                    severity=_normalize_severity(str(extra.get("severity", ""))),
                    # Triage metadata is OPTIONAL in the rule schema — the vendored ruleset
                    # declares none today, so these are empty on every real finding until that
                    # (CODEOWNERS-gated) ruleset gains metadata blocks.
                    confidence=_normalize_confidence(meta.get("confidence")),
                    subcategory=_first_str(meta.get("subcategory")).lower(),
                    cwe=_normalize_cwe(meta.get("cwe")),
                )
            )
        return findings


# Registry of available scanners by name. Add Trivy here; membership in
# ALLOWED_SCANNERS (policies) still gates whether each one actually runs.
_REGISTRY: dict[str, type[Scanner]] = {
    GitleaksScanner.name: GitleaksScanner,
    SemgrepScanner.name: SemgrepScanner,
}

# Cap on findings surfaced in the human/reviewer summary — semgrep can be noisy
# and the reviewer prompt has a ~12k budget. The full set still rides in the
# structured `findings` list; only the text summary is bounded.
_MAX_FINDINGS_SHOWN = 25


def build_scanners(names: Sequence[str] | None = None) -> list[Scanner]:
    """Instantiate the requested scanners, keeping only policy-allowed ones."""
    wanted = list(names) if names is not None else list(_REGISTRY)
    return [_REGISTRY[n]() for n in wanted if n in _REGISTRY and scanner_allowed(n)]


# The _hosttools convention, applied to sandboxed scanners: 0 = ran, nothing found;
# 1 = ran, reported findings. Anything else (127 missing binary, 2 crash, a timeout)
# means we learned nothing about this repo. Lifted from recon/security.py so the run
# gate and the durable-map recon share ONE exit-code classifier (see run_one).
_RAN = (0, 1)


def emitted_report(stdout: str) -> bool:
    """Generic well-formed-JSON check — the BASE completeness signal (`Scanner.reported_
    completely`) for a scanner with no report-shape of its own.

    **Empty or non-JSON stdout is NOT a report** — it means the scanner never produced one.
    A report reaches us through `sh -c "gitleaks …; cat report.json"`, so the sandbox exit
    code is `cat`'s, not the scanner's: a scanner that dies after creating an empty report
    file still exits 0 with empty stdout, and trusting that as "no findings" is the exact
    false-green the security gate must never emit. NOTE: this only proves the tail is valid
    JSON, NOT that the scan was COMPLETE — a real scanner (semgrep's `errors`, gitleaks'
    array shape) overrides `reported_completely` to check its own report; see red-team A.
    """
    s = stdout.strip()
    start = min((i for i in (s.find("["), s.find("{")) if i != -1), default=-1)
    if start == -1:
        return False
    try:
        json.loads(s[start:])
    except (json.JSONDecodeError, ValueError):
        return False
    return True


def run_one_with_cause(
    scanner: Scanner, sandbox: SandboxWorker, timeout: int | None = None
) -> tuple[list[Finding], bool, str]:
    """``run_one`` plus WHY it produced no verdict — ``""`` when it did.

    Measured 2026-08-09 over 193 runs: a scanner produced no verdict on **33 (17%)**, and
    `security_findings` was raised **zero** times. Those 33 parked 29 deliveries the hidden grader
    PASSED, and `security_unverified` is the ONLY thing disqualifying 25 of them from Layer-2
    class 2. So a 17% availability rate — not a security judgment — is the largest single source of
    discarded correct work in the corpus.

    Four different causes collapse into one ``ran=False`` here, and nothing recorded which. Naming
    one without measuring it is the defect F83 committed and then committed again in its own fix;
    this returns the cause so the 17% can be decomposed instead of guessed at.

    Deliberately does NOT alter the verdict: ``ran`` is computed exactly as before, and ``run_one``
    delegates here so the two can never disagree about what counts as a verdict.
    """
    try:
        result = sandbox.run(scanner.command(), timeout=timeout)
    except Exception as exc:
        return [], False, f"error:{type(exc).__name__}"
    if result.timed_out:
        return [], False, "timeout"
    if result.exit_code not in _RAN:
        return [], False, f"exit:{result.exit_code}"
    findings = scanner.parse(result.stdout)
    complete = scanner.reported_completely(result.stdout)
    # "incomplete" = a runnable exit code but the scanner's own report says it did not finish
    # (semgrep's `errors[]` non-empty — one unparseable file voids the whole repo's verdict).
    return findings, complete, "" if complete else "incomplete"


def run_one(
    scanner: Scanner, sandbox: SandboxWorker, timeout: int | None = None
) -> tuple[list[Finding], bool]:
    """``(findings, ran)`` for one scanner — exit-code classified, then completeness-checked.

    ``ran=True`` (a trustworthy verdict) requires BOTH a runnable exit code AND positive
    evidence the scanner produced a COMPLETE report of its own shape
    (``scanner.reported_completely`` — e.g. semgrep with an EMPTY ``errors`` array). A missing
    binary (exit 127), a crash, a timeout, exit-0-with-empty-stdout, or a **partial/errored
    scan** (semgrep failed to parse a target file) is ``ran=False`` — no verdict, never
    rounded down to clean-by-omission (red-team A). Any findings a partial report DID yield
    still ride along (the human sees them) but the run is UNAVAILABLE so the gate parks. A
    sandbox exception is likewise "no verdict", not a process crash.
    """
    findings, ran, _cause = run_one_with_cause(scanner, sandbox, timeout)
    return findings, ran


@dataclass(frozen=True)
class ScanOutcome:
    """The whole-run security verdict: the findings, a tri-state status, and which
    scanners produced no verdict. ``status`` is deny-by-default — ``unavailable`` wins over
    ``findings`` wins over ``clean`` (mirrors recon's ``DimensionResult.from_parts``)."""

    findings: list[Finding]
    status: SecurityStatus
    unavailable: tuple[str, ...]
    # WHY each of those produced no verdict — ``(scanner, cause)``. Additive and advisory: it never
    # participates in `status`. Added 2026-08-09 because a 17% no-verdict rate was discarding
    # correct work and four distinct causes were collapsed into one indistinguishable flag.
    unavailable_detail: tuple[tuple[str, str], ...] = ()


def run_scan(
    scanners: Sequence[Scanner], sandbox: SandboxWorker, *, timeout: int | None = None
) -> ScanOutcome:
    """Run every scanner and classify the run's security status tri-state.

    A scanner that produced no verdict (``run_one`` ``ran=False``) makes the whole run
    ``unavailable`` — "one scanner could not check" is not "the repo is clean". Findings
    that DID parse are still carried (a partial scan reports what it found AND that it was
    incomplete), so the gate parks on either the finding or the unverified status.
    """
    if not scanners:
        # Zero scanners is the empty-set inversion of this function's own rule: the loop
        # below never runs, so `unavailable` and `findings` are both empty and the status
        # falls through to "clean" — "we ran nothing" reported as "the repo is clean".
        # A caller with no scanners has not checked; say so.
        return ScanOutcome(
            findings=[],
            status="unavailable",
            unavailable=("(no scanner ran)",),
            unavailable_detail=(("(no scanner ran)", "no-scanner-configured"),),
        )
    findings: list[Finding] = []
    unavailable: list[str] = []
    detail: list[tuple[str, str]] = []
    for scanner in scanners:
        got, ran, cause = run_one_with_cause(scanner, sandbox, timeout=timeout)
        findings.extend(got)
        if not ran:
            unavailable.append(scanner.name)
            detail.append((scanner.name, cause))
    # UNCHANGED: `status` is computed from `unavailable`/`findings` exactly as before. The detail
    # rides alongside and must never enter this expression — pinned by test_scan_cause.py.
    status: SecurityStatus = "unavailable" if unavailable else ("findings" if findings else "clean")
    return ScanOutcome(
        findings=findings,
        status=status,
        unavailable=tuple(unavailable),
        unavailable_detail=tuple(detail),
    )


def run_scanners(
    scanners: Sequence[Scanner], sandbox: SandboxWorker, timeout: int | None = None
) -> list[Finding]:
    """Back-compat: the findings list only. Now delegates through ``run_scan`` so it gains
    ``run_one``'s exit-code discipline (a crashed scanner no longer parses to ``[]``)."""
    return run_scan(scanners, sandbox, timeout=timeout).findings


def format_findings(findings: Sequence[Finding]) -> str:
    """Human-readable summary for the reviewer prompt and the delivery report."""
    if not findings:
        return "No security findings."
    lines = [f"{len(findings)} security finding(s):"]
    for f in findings[:_MAX_FINDINGS_SHOWN]:
        loc = f"{f.path}:{f.line}" if f.path else "(unknown)"
        lines.append(f"- [{f.scanner}:{f.rule}] {loc} [{f.severity}] — {f.message}")
    extra = len(findings) - _MAX_FINDINGS_SHOWN
    if extra > 0:
        lines.append(f"- ... (+{extra} more)")
    return "\n".join(lines)
