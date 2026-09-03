"""What does pytest actually treat as a test file in THIS repo? (ADR-0036 amendment)

`testintegrity.is_test_file` hard-codes pytest's DEFAULT naming (`test_*.py` / `*_test.py`). pytest
collects by the `python_files` ini option, which a target may set to anything. On such a repo the
tamper baseline was EMPTY for the real tests, so the producer could rewrite its own acceptance test
undetected. Verified on a `python_files = ["check_*.py"]` repo, 2026-08-22:

    integrity_paths -> ['pyproject.toml']       # the test is not baselined
    tamper after rewriting the test to `assert True` -> []

That is the headline claim of `1f710222` ("the producer rewrote its acceptance test and
`tampered_integrity` returned []") still reproducing, because the fix addressed WHICH PATHS were
enumerated and not WHICH OF THEM COUNT AS TESTS.

ONE ORIGIN for the pytest-config table. Before this module the same four filenames were spelled out
in three places — `testintegrity._CONFIG_SECTIONS` (as hash targets), `languages/python.py` (as a
substring sniff), `recon/tests._COVERAGE_INPUTS` (as cache-key inputs). Nothing PARSED them; the
existing `_pytest_section` only scans lines so a section can be hashed.

DELIBERATELY NOT a general pytest-config reader. It answers one question — which files are tests —
and returns how it got the answer, so an inferred result can never look like a resolved one.
"""

from __future__ import annotations

import configparser
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

# pytest's own defaults, used when a repo says nothing.
DEFAULT_PYTHON_FILES: tuple[str, ...] = ("test_*.py", "*_test.py")

# In pytest's OWN precedence order: the first file carrying a pytest section wins outright. pytest
# does not merge them, and neither may we — merging would protect paths the target's real config
# excludes, and every extra baselined path is a terminal tamper park waiting for a regeneration.
_SOURCES: tuple[tuple[str, str], ...] = (
    ("pytest.ini", "pytest"),
    # pytest's `locate_config` reads the HIDDEN variant too, and it was in neither this table nor
    # `testintegrity._CONFIG_SECTIONS` — so a repo shipping one was unprotected, AND a producer
    # could CREATE one mid-run to shrink the suite without tripping the collection-control guard.
    (".pytest.ini", "pytest"),
    ("pyproject.toml", "tool.pytest.ini_options"),
    ("tox.ini", "pytest"),
    ("setup.cfg", "tool:pytest"),
)


@dataclass(frozen=True)
class PytestNaming:
    """The repo's answer, and HOW it was obtained — never one without the other.

    `source` is the config file that decided it, or `""` when nothing did. `resolved` is False for a
    default/fallback answer. A caller that shows a protected-looking run for an unprotected repo is
    the invisible-control failure this whole arc has been about, so the provenance is not optional
    and is carried to the operator.
    """

    python_files: tuple[str, ...]
    testpaths: tuple[str, ...]
    source: str
    resolved: bool
    note: str = ""

    def is_test_basename(self, rel: str) -> bool:
        """pytest's `fnmatch_ex`: a pattern containing a separator matches the WHOLE path.

        Basename-only matching made `python_files = tests/*.py` match nothing, so a repo using it
        was wholly unprotected while pytest collected its tests normally.
        """
        base = rel.rsplit("/", 1)[-1]
        return any(fnmatch(rel if "/" in pat else base, pat) for pat in self.python_files)

    def within_testpaths(self, rel: str) -> bool:
        """Where pytest LOOKS when given no arguments. NOT USED BY THE PROTECTED SET — see below.

        `resolve_test_surface` deliberately does not apply this: ADR-0054 forbids synthesising
        pytest path arguments, so `testpaths` never shapes a command we issue, and narrowing
        protection by it only ever removed real test files. Kept because it is part of the repo's
        declared configuration and rides the resolution record.

        Unmodellable ⇒ EVERYWHERE, never nowhere.

        THE FAILURE DIRECTION IS THE POINT. `testpaths` entries are rootdir-relative args that
        pytest globs, and a literal prefix match answered False for every one of `.`, `./tests`,
        `tests/*` and an absolute path — emptying the protected set on configurations ordinary
        repos ship. It cost this repo two files, because our own `pyproject.toml` sets
        `testpaths = ["packages", "apps"]`.

        Four probes disagreed with pytest and every one failed the same way: protect NOTHING. So
        anything not modelled exactly now widens to the whole tree instead. Over-protection here is
        an honest park; under-protection is a producer rewriting its own exam undetected.

        This is a safe FLOOR, not a fix for the modelling. The successor sources the collected set
        from `pytest --collect-only` and demotes this parser to a fallback.
        """
        if not self.testpaths:
            return True
        for raw in self.testpaths:
            tp = raw[2:] if raw.startswith("./") else raw
            tp = tp.rstrip("/")
            if not tp or tp == "." or tp.startswith("/") or any(c in tp for c in "*?["):
                return True  # cannot model it — assume pytest looks everywhere
            if rel == tp or rel.startswith(tp + "/"):
                return True
        return False


def _as_patterns(value: Any) -> tuple[str, ...]:
    """pytest accepts a list OR a whitespace/newline-separated string for these options."""
    if isinstance(value, str):
        return tuple(p for p in value.split() if p)
    if isinstance(value, (list, tuple)):
        return tuple(str(p) for p in value if str(p))
    return ()


def _from_toml(raw: str) -> tuple[dict[str, Any] | None, str]:
    try:
        data = tomllib.loads(raw)
    except (tomllib.TOMLDecodeError, ValueError, RecursionError, MemoryError) as exc:
        # A deeply-nested manifest blows the parser's recursion limit, and RecursionError is NOT a
        # ValueError — left uncaught it crashes the run rather than degrading (ADR-0035, the class
        # `recon/deps.py` already guards). The target repo is UNTRUSTED input.
        return None, f"pyproject.toml did not parse ({type(exc).__name__})"
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None, ""
    pytest_cfg = tool.get("pytest")
    if not isinstance(pytest_cfg, dict):
        return None, ""
    section = pytest_cfg.get("ini_options")
    return (section if isinstance(section, dict) else None), ""


def _from_ini(raw: str, header: str) -> tuple[dict[str, Any] | None, str]:
    # `interpolation=None`, which is what pytest's own `iniconfig` does. ConfigParser interpolates
    # `%`-values on ITEM ACCESS, not on parse, so `dict(parser[header])` used to raise PAST the
    # guard below — and `log_cli_format = %(asctime)s ...`, straight out of pytest's documentation,
    # crashed `plan_node` outright on a repo pytest itself is perfectly happy with. The `dict()` is
    # inside the try for the same reason: the failure is not where you expect it.
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(raw)
        if not parser.has_section(header):
            return None, ""
        return dict(parser[header]), ""
    except (configparser.Error, ValueError, RecursionError, MemoryError) as exc:
        return None, f"{header} did not parse ({type(exc).__name__})"


def resolve_naming(read_root: Any, exists: Any = None) -> PytestNaming:
    """Which files does pytest treat as tests here? `read_root(name) -> str` supplies file text.

    Takes a reader rather than a `Workspace` so this module stays dependency-free and testable
    against strings — and so a caller cannot accidentally hand it a path outside the clone.
    """
    notes: list[str] = []
    # EXISTENCE, not content. pytest: "pytest.ini files are always the source of configuration,
    # even if empty" — so a ZERO-BYTE `pytest.ini` is the configfile and `pyproject.toml` is
    # ignored (pytest even warns about it). Testing truthiness of the text could not tell an empty
    # file from an absent one, so one `touch pytest.ini` handed authority to a config pytest does
    # not read, and the protected set came from rules that were not in force.
    present = exists if exists is not None else (lambda n: bool(read_root(n)))
    for name, header in _SOURCES:
        raw = read_root(name)
        if not raw and not present(name):
            continue
        if not raw:
            if name in ("pytest.ini", ".pytest.ini"):
                return PytestNaming(DEFAULT_PYTHON_FILES, (), name, True, "; ".join(notes))
            continue
        if name.endswith(".toml"):
            section, note = _from_toml(raw)
        else:
            section, note = _from_ini(raw, header)
        if note:
            notes.append(note)
        if section is None:
            if name in ("pytest.ini", ".pytest.ini"):
                # AUTHORITATIVE EVEN WHEN EMPTY — pytest's own rule ("pytest.ini files are always
                # the source of configuration, even if empty"). Falling through let a producer void
                # pyproject's ini_options with a one-line comment file.
                return PytestNaming(DEFAULT_PYTHON_FILES, (), name, True, "; ".join(notes))
            continue
        files = _as_patterns(section.get("python_files")) or DEFAULT_PYTHON_FILES
        paths = _as_patterns(section.get("testpaths"))
        # A section that exists but sets neither option still RESOLVES: the repo has spoken and
        # chosen pytest's defaults. That is different from a repo we could not read.
        return PytestNaming(files, paths, name, True, "; ".join(notes))
    return PytestNaming(
        DEFAULT_PYTHON_FILES,
        (),
        "",
        False,
        "; ".join(notes) or "no pytest configuration found; assuming pytest's default naming",
    )
