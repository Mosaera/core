"""Scanner framework unit tests (parsing + policy gating), plus a Gitleaks
integration test that runs the scan container when one is reachable."""

from __future__ import annotations

import inspect
import os
from collections.abc import Sequence
from pathlib import Path

import pytest
from mosaera_core.sandbox import (
    DockerSandbox,
    SandboxResult,
    SandboxWorker,
)
from mosaera_core.tools.scan import (
    Finding,
    GitleaksScanner,
    ScanOutcome,
    SemgrepScanner,
    build_scanners,
    emitted_report,
    format_findings,
    run_one,
    run_scan,
    run_scanners,
)
from mosaera_policies import evaluate_gate

_DOCKER_BIN = os.environ.get("MOSAERA_DOCKER_BIN", "docker")
_SCAN_IMAGE = os.environ.get("MOSAERA_SCAN_IMAGE", "mosaera-scan:dev")
_SANDBOX_USER = os.environ.get("MOSAERA_SANDBOX_USER", "sandbox")
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Skip when the daemon is down OR the scan image isn't built (self-skip, not an exit-125 fail).
# The gate lives in the repo-root conftest (#58): probed once, reason printed,
# and an ERROR rather than a skip when MOSAERA_INTEGRATION=required.
requires_docker = pytest.mark.requires_docker(_SCAN_IMAGE)

_GITLEAKS_JSON = """[
 {"RuleID":"github-pat","Description":"GitHub PAT","StartLine":1,"File":"/work/config.py"},
 {"RuleID":"aws-key","Description":"AWS key","StartLine":4,"File":"/work/src/app.py"}
]"""


def test_gitleaks_parse() -> None:
    findings = GitleaksScanner().parse(_GITLEAKS_JSON)
    assert len(findings) == 2
    assert findings[0].scanner == "gitleaks"
    assert findings[0].rule == "github-pat"
    assert findings[0].path == "config.py"  # /work/ prefix stripped
    assert findings[0].line == 1
    assert findings[1].path == "src/app.py"


def test_parse_tolerates_noise_and_empty() -> None:
    assert GitleaksScanner().parse("") == []
    assert GitleaksScanner().parse("not json") == []
    assert GitleaksScanner().parse("log line\n[]") == []


_SEMGREP_JSON = """{"results":[
 {"check_id":"dangerous-eval","path":"/work/app.py","start":{"line":7},
  "extra":{"message":"eval() executes arbitrary code","severity":"ERROR"}},
 {"check_id":"dangerous-subprocess-shell","path":"/work/util.py","start":{"line":12},
  "extra":{"message":"shell=True is a shell-injection risk"}}
],"errors":[]}"""


def test_semgrep_parse() -> None:
    # Semgrep emits an OBJECT {"results":[...]}, not a top-level array.
    findings = SemgrepScanner().parse(_SEMGREP_JSON)
    assert len(findings) == 2
    assert findings[0].scanner == "semgrep"
    assert findings[0].rule == "dangerous-eval"
    assert findings[0].path == "app.py"  # /work/ prefix stripped
    assert findings[0].line == 7
    assert findings[1].path == "util.py"


def test_semgrep_parse_tolerates_noise_and_empty() -> None:
    assert SemgrepScanner().parse("") == []
    assert SemgrepScanner().parse("not json") == []
    assert SemgrepScanner().parse('log\n{"results":[]}') == []


def test_format_findings_caps_long_lists() -> None:
    many = [Finding("semgrep", f"r{i}", f"f{i}.py", i, "m") for i in range(40)]
    text = format_findings(many)
    assert "40 security finding(s):" in text  # honest total
    assert "(+15 more)" in text  # 40 - 25 shown


def test_format_findings() -> None:
    assert format_findings([]) == "No security findings."
    text = format_findings([Finding("gitleaks", "aws-key", "a.py", 3, "AWS key")])
    assert "1 security finding" in text
    assert "gitleaks:aws-key" in text
    assert "a.py:3" in text


def test_build_scanners_respects_policy() -> None:
    # gitleaks + semgrep are in ALLOWED_SCANNERS; an unknown/denied one is dropped.
    assert [s.name for s in build_scanners(["gitleaks"])] == ["gitleaks"]
    assert [s.name for s in build_scanners(["semgrep"])] == ["semgrep"]
    assert build_scanners(["nmap"]) == []
    # Default = all allowed (order follows the registry).
    assert {s.name for s in build_scanners()} == {"gitleaks", "semgrep"}


# --- Severity (ADR-0076): carried as DATA; the gate does not tier on it in MR-1. ---


def test_gitleaks_findings_are_critical() -> None:
    # A located secret is inherently critical (gitleaks emits no per-finding severity).
    findings = GitleaksScanner().parse(_GITLEAKS_JSON)
    assert [f.severity for f in findings] == ["critical", "critical"]


def test_semgrep_parse_severity_normalized() -> None:
    findings = SemgrepScanner().parse(_SEMGREP_JSON)
    assert findings[0].severity == "high"  # extra.severity "ERROR" -> high
    assert findings[1].severity == "medium"  # no severity in extra -> deny-by-default medium


def test_finding_as_dict_includes_severity() -> None:
    d = Finding("semgrep", "r", "a.py", 3, "m", "high").as_dict()
    assert d["severity"] == "high"


def test_finding_positional_five_args_defaults_severity() -> None:
    # The pre-ADR-0076 positional shape stays valid; severity defaults to "medium".
    assert Finding("gitleaks", "r", "a.py", 3, "m").severity == "medium"


def test_format_findings_shows_severity() -> None:
    text = format_findings([Finding("gitleaks", "aws-key", "a.py", 3, "AWS key", "critical")])
    assert "[critical]" in text


# --- Triage metadata (confidence / subcategory / cwe): carried as DATA, like severity. ---
# The rule schema makes all three OPTIONAL and permits `subcategory`/`cwe` as either a bare
# string or a list, so every shape below is one semgrep actually emits.

_SEMGREP_META_JSON = """{"results":[
 {"check_id":"sql-injection","path":"/work/db.py","start":{"line":9},
  "extra":{"message":"tainted SQL","severity":"ERROR","metadata":{
    "confidence":"HIGH","subcategory":["vuln"],
    "cwe":["CWE-89: Improper Neutralization of Special Elements used in an SQL Command"],
    "owasp":["A03:2021 - Injection"],"technology":["python"]}}}
],"errors":[]}"""


def test_semgrep_parse_carries_triage_metadata() -> None:
    (finding,) = SemgrepScanner().parse(_SEMGREP_META_JSON)
    assert finding.confidence == "high"  # HIGH -> lowercased vocabulary
    assert finding.subcategory == "vuln"  # one-element list -> the string
    assert finding.cwe == (
        "CWE-89: Improper Neutralization of Special Elements used in an SQL Command",
    )


def test_semgrep_parse_defaults_triage_metadata_when_absent() -> None:
    # The vendored ruleset declares no metadata today, so this is the REAL production shape:
    # absent must mean "the scanner declared nothing", never a fabricated tier.
    findings = SemgrepScanner().parse(_SEMGREP_JSON)
    assert [f.confidence for f in findings] == ["", ""]
    assert [f.subcategory for f in findings] == ["", ""]
    assert [f.cwe for f in findings] == [(), ()]


@pytest.mark.parametrize(
    "metadata",
    ['"a string"', "[1, 2]", "null", "42"],
    ids=["string", "list", "null", "int"],
)
def test_semgrep_parse_survives_a_non_dict_metadata(metadata: str) -> None:
    # Mirrors test_semgrep_parse_survives_a_non_dict_extra: malformed metadata degrades to
    # "declared nothing", it must never raise mid-scan and lose the whole report.
    stdout = (
        '{"results":[{"check_id":"r","path":"/work/a.py","start":{"line":1},'
        f'"extra":{{"message":"m","metadata":{metadata}}}}}],"errors":[]}}'
    )
    (finding,) = SemgrepScanner().parse(stdout)
    assert (finding.confidence, finding.subcategory, finding.cwe) == ("", "", ())


def test_semgrep_parse_accepts_both_metadata_spellings() -> None:
    stdout = (
        '{"results":[{"check_id":"r","path":"/work/a.py","start":{"line":1},'
        '"extra":{"message":"m","metadata":{"subcategory":"AUDIT","cwe":"CWE-798"}}}],'
        '"errors":[]}'
    )
    (finding,) = SemgrepScanner().parse(stdout)
    assert finding.subcategory == "audit"  # bare string, same result as the list spelling
    assert finding.cwe == ("CWE-798",)


def test_semgrep_parse_drops_an_unrecognized_confidence() -> None:
    # Unknown confidence is "" (unknown), NOT rounded to a tier — the deliberate divergence
    # from severity's deny-by-default, since nothing tiers on confidence.
    stdout = (
        '{"results":[{"check_id":"r","path":"/work/a.py","start":{"line":1},'
        '"extra":{"message":"m","metadata":{"confidence":"VERY HIGH"}}}],"errors":[]}'
    )
    (finding,) = SemgrepScanner().parse(stdout)
    assert finding.confidence == ""


def test_finding_as_dict_includes_triage_metadata() -> None:
    d = Finding("semgrep", "r", "a.py", 3, "m", "high", "low", "audit", ("CWE-798",)).as_dict()
    assert d["confidence"] == "low"
    assert d["subcategory"] == "audit"
    # A list, not a tuple: this dict is JSON-serialized into the LangGraph checkpoint.
    assert d["cwe"] == ["CWE-798"]


def test_finding_positional_five_args_defaults_triage_metadata() -> None:
    # The new fields extend the same positional-compatibility guarantee severity has.
    f = Finding("gitleaks", "r", "a.py", 3, "m")
    assert (f.confidence, f.subcategory, f.cwe) == ("", "", ())


def test_gitleaks_declares_no_triage_metadata() -> None:
    # gitleaks has no metadata channel; assigning it a subcategory here would be this module
    # inventing a vocabulary rather than carrying the scanner's own.
    for f in GitleaksScanner().parse(_GITLEAKS_JSON):
        assert (f.confidence, f.subcategory, f.cwe) == ("", "", ())


# --- The two negative guarantees: this data reaches NEITHER the reviewer prompt NOR the gate. ---


def test_triage_metadata_does_not_change_the_rendered_findings() -> None:
    # format_findings is the SINGLE renderer feeding both the reviewer prompt and the report,
    # so an unchanged rendering is what makes "the reviewer prompt is byte-identical" true.
    plain = Finding("semgrep", "sql-injection", "db.py", 9, "tainted SQL", "high")
    enriched = Finding(
        "semgrep", "sql-injection", "db.py", 9, "tainted SQL", "high", "high", "vuln", ("CWE-89",)
    )
    assert format_findings([enriched]) == format_findings([plain])


def test_triage_metadata_cannot_reach_the_delivery_gate() -> None:
    # ADR-0076 rejected tiering the gate on scanner severity: it would LOOSEN the gate (a
    # finding that parks today would ship), a non-monotonic change to a trust boundary. The
    # same binds here. The gate takes no triage parameter at all — the only channel from a
    # finding to it is the COUNT — so a LOW-confidence "audit" finding must park identically
    # to any other. If a future MR wires tiering in, this test is the one that must be
    # deliberately changed rather than quietly passing.
    params = set(inspect.signature(evaluate_gate).parameters)
    assert params.isdisjoint({"confidence", "subcategory", "cwe", "severity", "findings"})

    parked = evaluate_gate(
        tests_passed=True,
        reviewer_verdict="APPROVE",
        findings_count=1,
        iteration=1,
        max_iterations=5,
    )
    assert "security_findings" in parked.reasons


# --- Tri-state scan status (ADR-0076): "we did not look" is never "clean". ---


class _FakeSandbox(SandboxWorker):
    """Returns a single scripted result for every run — drives one scanner's exit/stdout."""

    def __init__(self, exit_code: int, stdout: str, *, timed_out: bool = False) -> None:
        self._result = SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr="",
            duration_s=0.0,
            timed_out=timed_out,
            network_isolated=True,
        )

    def run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
        readonly_work: bool = False,
    ) -> SandboxResult:
        return self._result

    def run_setup(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
    ) -> SandboxResult:
        return self._result


class _SeqSandbox(_FakeSandbox):
    """Pops one scripted result (or raises a scripted exception) per run call — lets a
    multi-scanner run_scan mix a real verdict with a silently-failing scanner."""

    def __init__(self, results: list[SandboxResult | Exception]) -> None:
        self._results = list(results)

    def run(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        timeout: int | None = None,
        image: str | None = None,
        readonly_work: bool = False,
    ) -> SandboxResult:
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _result(exit_code: int, stdout: str, *, timed_out: bool = False) -> SandboxResult:
    return SandboxResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr="",
        duration_s=0.0,
        timed_out=timed_out,
        network_isolated=True,
    )


def test_emitted_report_truth_table() -> None:
    assert emitted_report("") is False
    assert emitted_report("   \n") is False
    assert emitted_report("not json at all") is False
    assert emitted_report("[]") is True
    assert emitted_report('{"results":[]}') is True
    assert emitted_report("log noise\n[]") is True  # leading noise tolerated


def test_run_one_classifies_exit_and_report() -> None:
    scanner = GitleaksScanner()
    # ran + findings
    got, ran = run_one(scanner, _FakeSandbox(1, _GITLEAKS_JSON))
    assert ran is True and len(got) == 2
    # ran + clean (well-formed empty report at exit 0)
    assert run_one(scanner, _FakeSandbox(0, "[]")) == ([], True)
    # no verdict: bad exit / empty stdout / timeout / sandbox exception
    assert run_one(scanner, _FakeSandbox(127, "")) == ([], False)
    assert run_one(scanner, _FakeSandbox(0, "")) == ([], False)
    assert run_one(scanner, _FakeSandbox(0, "[]", timed_out=True)) == ([], False)
    assert run_one(scanner, _SeqSandbox([RuntimeError("docker down")])) == ([], False)


def test_run_scan_with_no_scanners_is_unavailable_not_clean() -> None:
    # The empty-set inversion of this module's own rule. The loop never runs, so `findings`
    # and `unavailable` are both empty and the status used to fall through to "clean" —
    # "we ran nothing" reported as "the repo is clean". Zero scanners is not a clean bill.
    out = run_scan([], _FakeSandbox(0, "[]"))
    assert out.status == "unavailable"
    assert out.findings == []


def test_run_scan_clean() -> None:
    out = run_scan([GitleaksScanner()], _FakeSandbox(0, "[]"))
    assert out == ScanOutcome(findings=[], status="clean", unavailable=())


def test_run_scan_findings() -> None:
    out = run_scan([GitleaksScanner()], _FakeSandbox(1, _GITLEAKS_JSON))
    assert out.status == "findings" and len(out.findings) == 2 and out.unavailable == ()


def test_run_scan_unavailable_on_bad_exit() -> None:
    out = run_scan([GitleaksScanner()], _FakeSandbox(127, ""))
    assert out.status == "unavailable" and out.unavailable == ("gitleaks",)


def test_run_scan_unavailable_on_empty_stdout_at_exit0() -> None:
    out = run_scan([GitleaksScanner()], _FakeSandbox(0, "nothing scanned"))
    assert out.status == "unavailable"


def test_run_scan_unavailable_on_sandbox_exception() -> None:
    out = run_scan([GitleaksScanner()], _SeqSandbox([RuntimeError("docker unreachable")]))
    assert out.status == "unavailable" and out.unavailable == ("gitleaks",)


def test_run_scan_partial_unavailable_keeps_the_parsed_findings() -> None:
    # gitleaks reports findings; semgrep silently fails. The run is UNVERIFIED (one scanner
    # gave no verdict) but the findings that DID parse are still carried.
    out = run_scan(
        [GitleaksScanner(), SemgrepScanner()],
        _SeqSandbox([_result(1, _GITLEAKS_JSON), _result(2, "crash")]),
    )
    assert out.status == "unavailable"
    assert out.unavailable == ("semgrep",)
    assert len(out.findings) == 2  # gitleaks' findings survive


def test_run_scanners_delegates_to_run_scan() -> None:
    # Back-compat: run_scanners returns just the findings list, now with run_one discipline.
    findings = run_scanners([GitleaksScanner()], _FakeSandbox(1, _GITLEAKS_JSON))
    assert [f.rule for f in findings] == ["github-pat", "aws-key"]
    # a crashed scanner no longer parses to a false-clean empty list vs. a real clean one:
    assert run_scanners([GitleaksScanner()], _FakeSandbox(127, "")) == []


# --- Report COMPLETENESS (ADR-0076 red-team A): "ran, but not to completion" != clean. ---

# semgrep exits 0 but reports a file it could NOT parse — a partial scan, not a clean one.
_SEMGREP_ERRORS_JSON = (
    '{"version":"1.55.2","results":[],'
    '"errors":[{"code":2,"type":"SyntaxError","message":"cannot parse",'
    '"path":"/work/secrets.py"}],'
    '"paths":{"skipped":[{"path":"/work/secrets.py","reason":"syntax_error"}]}}'
)
# semgrep that DID find something in one file but errored on another — still incomplete.
_SEMGREP_FINDING_PLUS_ERRORS_JSON = (
    '{"results":[{"check_id":"x","path":"/work/a.py","start":{"line":1},'
    '"extra":{"message":"m","severity":"ERROR"}}],'
    '"errors":[{"message":"could not parse /work/b.py"}]}'
)


def test_semgrep_reported_completely() -> None:
    s = SemgrepScanner()
    assert s.reported_completely('{"results":[],"errors":[]}') is True
    assert s.reported_completely('{"results":[]}') is True  # errors absent → complete
    # a non-empty errors array (a file it could not parse) → NOT complete
    assert s.reported_completely(_SEMGREP_ERRORS_JSON) is False
    # a body that is not a report shape (no results key / bare object) → NOT complete
    assert s.reported_completely("{}") is False
    assert s.reported_completely('{"error":"boom"}') is False
    assert s.reported_completely("") is False
    # red-team round 2: a malformed (non-list) errors channel fails CLOSED, never "no errors"
    assert s.reported_completely('{"results":[],"errors":null}') is False
    assert s.reported_completely('{"results":[],"errors":{}}') is False
    assert s.reported_completely('{"results":[],"errors":""}') is False


def test_semgrep_command_disables_the_silent_size_skip() -> None:
    # red-team round 2 stopgap: without this, semgrep silently skips files >1MB (errors:[])
    # and a vuln in a big file reads clean. 0 = no limit → the big file is scanned or the
    # scan times out and parks (fails safe).
    cmd = SemgrepScanner().command()
    assert "--max-target-bytes" in cmd
    assert cmd[cmd.index("--max-target-bytes") + 1] == "0"


def test_gitleaks_reported_completely() -> None:
    g = GitleaksScanner()
    assert g.reported_completely("[]") is True
    assert g.reported_completely(_GITLEAKS_JSON) is True
    # gitleaks' report is a top-level array; an object / garbage / empty is not its report
    assert g.reported_completely('{"results":[]}') is False
    assert g.reported_completely("boom") is False
    assert g.reported_completely("") is False


def test_run_scan_semgrep_partial_errors_is_unavailable_not_clean() -> None:
    # THE red-team-A regression: exit 0 + empty results BUT a non-empty errors array must be
    # UNAVAILABLE (a file went unscanned), never "clean". Before the fix this shipped as clean.
    out = run_scan([SemgrepScanner()], _FakeSandbox(0, _SEMGREP_ERRORS_JSON))
    assert out.status == "unavailable"
    assert out.unavailable == ("semgrep",)


def test_run_scan_semgrep_finding_plus_errors_keeps_finding_but_is_unavailable() -> None:
    # A partial scan that DID find something: the finding rides along (the human sees it) but
    # the run is still UNAVAILABLE (deny-by-default) because a target went unscanned.
    out = run_scan([SemgrepScanner()], _FakeSandbox(0, _SEMGREP_FINDING_PLUS_ERRORS_JSON))
    assert out.status == "unavailable"
    assert len(out.findings) == 1


def test_semgrep_parse_survives_a_non_dict_extra() -> None:
    # A malformed `extra` (a list, not an object) must not crash the parser (fails closed).
    findings = SemgrepScanner().parse(
        '{"results":[{"check_id":"x","path":"/work/a.py","start":{"line":1},"extra":[1,2]}]}'
    )
    assert len(findings) == 1 and findings[0].severity == "medium"


@requires_docker
def test_gitleaks_detects_planted_secret(tmp_path: Path) -> None:
    # The scan container can only bind-mount Windows-filesystem paths via
    # docker.exe; place the workspace under the repo tree in that case.
    if _DOCKER_BIN.lower().endswith(".exe"):
        base = _REPO_ROOT / ".mosaera" / "_pytest_scan"
        base.mkdir(parents=True, exist_ok=True)
        workdir = base / os.urandom(6).hex()
        workdir.mkdir()
    else:
        workdir = tmp_path
    (workdir / "config.py").write_text(
        'token = "ghp_1a2b3c4d5e6f7g8h9i0jK1L2M3N4O5P6Q7R8"\n', encoding="utf-8"
    )
    sandbox = DockerSandbox(
        workdir, image=_SCAN_IMAGE, docker_bin=_DOCKER_BIN, default_timeout=120, user=_SANDBOX_USER
    )
    findings = run_scanners(build_scanners(["gitleaks"]), sandbox)
    assert any(f.rule == "github-pat" and f.path == "config.py" for f in findings)


def _scan_workdir(tmp_path: Path) -> Path:
    if _DOCKER_BIN.lower().endswith(".exe"):
        base = _REPO_ROOT / ".mosaera" / "_pytest_scan"
        base.mkdir(parents=True, exist_ok=True)
        d = base / os.urandom(6).hex()
        d.mkdir()
        return d
    return tmp_path


@requires_docker
def test_semgrep_detects_planted_vuln(tmp_path: Path) -> None:
    # A vulnerable pattern the vendored local ruleset flags — proving semgrep
    # runs with bundled rules under --network none (no registry fetch).
    workdir = _scan_workdir(tmp_path)
    (workdir / "app.py").write_text(
        "import subprocess\n\n\ndef run(cmd):\n    subprocess.run(cmd, shell=True)\n",
        encoding="utf-8",
    )
    sandbox = DockerSandbox(
        workdir, image=_SCAN_IMAGE, docker_bin=_DOCKER_BIN, default_timeout=180, user=_SANDBOX_USER
    )
    findings = run_scanners(build_scanners(["semgrep"]), sandbox)
    assert any(f.rule == "dangerous-subprocess-shell" and f.path == "app.py" for f in findings)
