#!/usr/bin/env python3
"""Engine version bump + consistency check (ADR-0055, ADR-0088).

Why this exists. ADR-0055 named `mosaera_core.__version__` the single source of truth and said
"all 7 packages move together — one product", then left the bump as a hand-edit across ten files.
It drifted immediately and twice: the 0.5.0→0.6.0 bump (`c0e280c`) missed the workspace root, which
sat a release behind until `45f46c7` fixed it two weeks later; `apps/web/package.json`,
`mosaera_agents.__version__` and the FastAPI `version=` argument each sat at `0.1.0` through two
releases. A mechanically-checkable invariant deserves a mechanical tool.

Two modes:

    uv run python scripts/bump_version.py --check          # verify only, no writes (CI calls this)
    uv run python scripts/bump_version.py 0.6.1            # rewrite every version string
    uv run python scripts/bump_version.py 0.6.1 --maturity rc

What it deliberately does NOT do: create or push the git tag. A bump is a deliberate human act
(ADR-0055), and a script that tags edges toward automatic release authority — which
*Deterministic Final Authority* keeps with the human. It prints the command for you to run.

It also does not fill in the benchmark snapshot. It writes the CHANGELOG heading with the snapshot
line left as a TODO, so a release physically cannot be written without confronting the evidence
requirement (ADR-0055: every release carries its benchmark snapshot; ADR-0061: a rate is only a
result when the distribution it bounds is named).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CORE_INIT = ROOT / "packages" / "core" / "mosaera_core" / "__init__.py"
WEB_PACKAGE_JSON = ROOT / "apps" / "web" / "package.json"
CHANGELOG = ROOT / "CHANGELOG.md"

# ADR-0088's closed ladder. Kept in step with mosaera_core.MATURITY_CHANNELS (asserted by
# packages/core/tests/test_cli_version.py, so the two cannot silently diverge).
MATURITY_CHANNELS = ("alpha", "beta", "rc", "stable")

# PEP 440 release segment, restricted to the plain X.Y.Z the repo actually uses. Deliberately
# NARROWER than PEP 440 allows: no epochs, no `.postN`/`.devN`, and no `aN`/`bN`/`rcN` pre-release
# suffix — maturity lives in `__maturity__` (ADR-0088), not in the number, so that every
# pyproject version stays a plain release and `uv` has nothing to normalize. A SemVer-style
# `0.6.1-beta.1` is rejected here precisely because `packaging` would silently rewrite it to
# `0.6.1b1` in metadata and lockfiles while `__version__` kept the hyphen — drift by normalization.
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

_CORE_VERSION_RE = re.compile(r'^__version__:\s*Final\[str\]\s*=\s*"([^"]+)"$', re.MULTILINE)
_CORE_MATURITY_RE = re.compile(r'^__maturity__:\s*Final\[str\]\s*=\s*"([^"]+)"$', re.MULTILINE)

# For reading a PAST revision, where the annotation may not exist yet (`__version__ = "0.6.0"`
# predates ADR-0088). Deliberately looser than the write-side regexes: a guard that silently
# skips because history is spelled differently is worse than no guard at all.
_ANY_VERSION_RE = re.compile(r'^__version__(?:\s*:[^=]+)?\s*=\s*"([^"]+)"$', re.MULTILINE)
_PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"$', re.MULTILINE)


def _pyprojects() -> list[Path]:
    """The 7 workspace pyprojects ADR-0055 keeps in lockstep."""
    found = [
        ROOT / "pyproject.toml",
        ROOT / "apps" / "api" / "pyproject.toml",
        *sorted((ROOT / "packages").glob("*/pyproject.toml")),
    ]
    return [p for p in found if p.is_file()]


def _parse(version: str) -> tuple[int, int, int]:
    m = _VERSION_RE.match(version)
    if not m:
        raise SystemExit(
            f"error: {version!r} is not a plain X.Y.Z release version.\n"
            "  Maturity belongs in __maturity__ (ADR-0088), not in the number: a SemVer-style\n"
            "  '0.6.1-beta.1' is invalid PEP 440 and `uv` would normalize it to '0.6.1b1' in\n"
            "  metadata while __version__ kept the hyphen. Use `--maturity` instead."
        )
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _current_version() -> str:
    m = _CORE_VERSION_RE.search(CORE_INIT.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f'error: no `__version__: Final[str] = "..."` in {CORE_INIT}')
    return m.group(1)


def _current_maturity() -> str:
    m = _CORE_MATURITY_RE.search(CORE_INIT.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f'error: no `__maturity__: Final[str] = "..."` in {CORE_INIT}')
    return m.group(1)


def _collect() -> dict[str, str]:
    """Every version string that must agree, keyed by repo-relative path."""
    found: dict[str, str] = {"packages/core/mosaera_core/__init__.py": _current_version()}
    for p in _pyprojects():
        m = _PYPROJECT_VERSION_RE.search(p.read_text(encoding="utf-8"))
        if m:
            found[p.relative_to(ROOT).as_posix()] = m.group(1)
    if WEB_PACKAGE_JSON.is_file():
        data = json.loads(WEB_PACKAGE_JSON.read_text(encoding="utf-8"))
        found["apps/web/package.json"] = data.get("version", "")
    return found


def check() -> int:
    """Verify-only. Non-zero if any version string disagrees or maturity is off-ladder."""
    found = _collect()
    expected = found["packages/core/mosaera_core/__init__.py"]
    problems: list[str] = []

    n_pyprojects = sum(1 for k in found if k.endswith("pyproject.toml"))
    if n_pyprojects != 7:
        problems.append(f"expected 7 workspace pyprojects, found {n_pyprojects}")

    drifted = {k: v for k, v in found.items() if v != expected}
    problems += [f"{k}: {v!r} != {expected!r}" for k, v in sorted(drifted.items())]

    maturity = _current_maturity()
    if maturity not in MATURITY_CHANNELS:
        problems.append(f"__maturity__ {maturity!r} not in {MATURITY_CHANNELS} (ADR-0088)")

    if problems:
        print("Version consistency FAILED (ADR-0055: all packages move together):\n")
        for p in problems:
            print(f"  {p}")
        print("\nFix with: uv run python scripts/bump_version.py <version>")
        return 1

    print(f"Version consistency OK: {expected} ({maturity}) across {len(found)} files.")
    return 0


def _write_changelog_stub(version: str, maturity: str) -> None:
    """Insert a release heading below [Unreleased], snapshot left as an explicit TODO."""
    text = CHANGELOG.read_text(encoding="utf-8")
    heading = f"## {version} — {date.today().isoformat()} — TODO headline"
    if f"\n## {version} " in text:
        print(f"  CHANGELOG.md: '## {version}' already present, left alone")
        return
    stub = (
        f"{heading}\n\n"
        f"**Benchmark snapshot: TODO** — required by ADR-0055. Name the suite, the run count,\n"
        f"and the posture configuration; a rate with no named distribution is not a result\n"
        f"(ADR-0061).\n"
        f"Maturity channel: `{maturity}` (ADR-0088).\n\n"
        f"- TODO: what changed in this release.\n\n"
    )
    marker = "\n## "
    idx = text.find(marker, text.find("## [Unreleased]") + 1)
    if idx == -1:
        raise SystemExit("error: could not find an insertion point in CHANGELOG.md")
    CHANGELOG.write_text(text[: idx + 1] + stub + text[idx + 1 :], encoding="utf-8")
    print(f"  CHANGELOG.md: inserted '{heading}'")


def bump(version: str, maturity: str | None) -> int:
    current = _current_version()
    if _parse(version) <= _parse(current):
        raise SystemExit(
            f"error: {version} is not greater than the current {current}.\n"
            "  Versions are monotonic: 0.6.0 is already stamped into run receipts, the benchmark\n"
            "  trend, and the runs.engine_version column. Going backwards orphans that audit chain."
        )
    if maturity is not None and maturity not in MATURITY_CHANNELS:
        raise SystemExit(f"error: --maturity must be one of {MATURITY_CHANNELS} (ADR-0088)")

    print(f"Bumping {current} -> {version}")
    text = CORE_INIT.read_text(encoding="utf-8")
    text = _CORE_VERSION_RE.sub(f'__version__: Final[str] = "{version}"', text, count=1)
    if maturity is not None:
        text = _CORE_MATURITY_RE.sub(f'__maturity__: Final[str] = "{maturity}"', text, count=1)
    CORE_INIT.write_text(text, encoding="utf-8")
    print(f"  {CORE_INIT.relative_to(ROOT)}")

    for p in _pyprojects():
        raw = p.read_text(encoding="utf-8")
        p.write_text(
            _PYPROJECT_VERSION_RE.sub(f'version = "{version}"', raw, count=1), encoding="utf-8"
        )
        print(f"  {p.relative_to(ROOT)}")

    if WEB_PACKAGE_JSON.is_file():
        raw = WEB_PACKAGE_JSON.read_text(encoding="utf-8")
        # Targeted line rewrite, not json.dumps — a full re-serialize would reformat the file
        # and bury the one-line bump in noise.
        WEB_PACKAGE_JSON.write_text(
            re.sub(
                r'^(\s*)"version":\s*"[^"]+"',
                rf'\1"version": "{version}"',
                raw,
                count=1,
                flags=re.MULTILINE,
            ),
            encoding="utf-8",
        )
        print(f"  {WEB_PACKAGE_JSON.relative_to(ROOT)}")

    _write_changelog_stub(version, maturity or _current_maturity())

    print(
        f"\nNext, in order:\n"
        f"  1. Fill the CHANGELOG benchmark snapshot (a bump without one is not a release).\n"
        f"  2. make fmt-check lint typecheck test\n"
        f"  3. Commit, MR, merge.\n"
        f"  4. AFTER merge, tag it yourself — this script will not:\n"
        f"     git tag -a v{version} -m '{version} — <headline>' && git push origin v{version}\n"
    )
    return 0


def verify_record(base_ref: str, *, strict: bool = False) -> int:
    """If this branch bumped the version, require a matching CHANGELOG heading.

    The one check that genuinely cannot live in a unit test: it compares the working tree against
    the merge-request base, so it needs git history. Consistency (`--check`) is NOT duplicated
    here — it runs inside `make ci` via packages/core/tests/test_cli_version.py, per the
    .gitlab-ci.yml rule that new guards land in the Makefile only.

    ``strict`` (CI) turns every "could not look" into a FAILURE. Four separate paths here used to
    print a note and return 0 — no git, an unreadable base ref, an unparsable ``__version__`` —
    and the CI job runs *only when `__init__.py` changed*, i.e. exactly when it must actually
    verify something. A shallow-clone hiccup was therefore indistinguishable from a verified
    release, and the job's single real run to date was vacuous (the version had not moved, so it
    took the `old == new` exit). Locally the lenient behaviour is right: a developer running this
    on a detached tree should get a note, not a red herring.
    """
    import shutil
    import subprocess

    def _vacant(message: str) -> int:
        # "We could not check" is a PASS locally and a FAILURE in CI. Spelling both the same is
        # the green-by-vacancy shape this repo has now measured in three separate checks.
        print(f"{'Release record FAILED' if strict else 'note'}: {message}")
        return 1 if strict else 0

    git = shutil.which("git")
    if git is None:
        return _vacant("git not on PATH, so the release record could not be verified.")
    try:
        before = subprocess.run(  # noqa: S603 — full path from shutil.which; no shell
            [git, "show", f"{base_ref}:packages/core/mosaera_core/__init__.py"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        ).stdout
    except subprocess.CalledProcessError as exc:
        return _vacant(f"cannot read {base_ref} ({exc}), so the release record is unverified.")

    m = _ANY_VERSION_RE.search(before)
    old = m.group(1) if m else None
    new = _current_version()
    if old is None:
        return _vacant(f"no parsable __version__ at {base_ref}; the release record is unverified.")
    if old == new:
        print(f"Release record OK: version unchanged at {new}.")
        return 0

    if f"\n## {new} " not in CHANGELOG.read_text(encoding="utf-8"):
        print(
            f"Release record FAILED: version moved {old} -> {new}, but CHANGELOG.md has no\n"
            f"  '## {new} — ...' heading.\n\n"
            "ADR-0055: every release carries its benchmark snapshot. A bump with no entry is a\n"
            "version number with no evidence behind it. See docs/runbooks/versioning.md."
        )
        return 1

    print(f"Release record OK: {old} -> {new} with a CHANGELOG entry.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bump_version.py",
        description="Move every engine version string together (ADR-0055) and record the release.",
    )
    parser.add_argument("version", nargs="?", help="the new X.Y.Z version (omit with --check)")
    parser.add_argument(
        "--maturity",
        choices=MATURITY_CHANNELS,
        default=None,
        help="also move the ADR-0088 maturity channel (requires the same benchmark evidence)",
    )
    parser.add_argument(
        "--check", action="store_true", help="verify consistency only; write nothing"
    )
    parser.add_argument(
        "--verify-record",
        metavar="BASE_REF",
        default=None,
        help="if the version moved since BASE_REF, require a matching CHANGELOG heading (CI)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="with --verify-record: treat 'could not check' as a FAILURE (what CI passes)",
    )
    args = parser.parse_args(argv)

    if args.verify_record:
        if args.version:
            parser.error("--verify-record takes no version argument")
        return verify_record(args.verify_record, strict=args.strict)
    if args.check:
        if args.version:
            parser.error("--check takes no version argument")
        return check()
    if not args.version:
        parser.error("a version argument is required (or use --check)")
    return bump(args.version, args.maturity)


if __name__ == "__main__":
    sys.exit(main())
