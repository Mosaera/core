"""Test-integrity baseline: detect a coder making validation go green by weakening it.

ADR-0034 lets an autonomous run deliver over a silent reviewer when the validation was a
real suite that PASSED. That is only sound if the coder cannot *manufacture* a green suite.
It can, three ways, and none touch the delivery gate directly:

  1. edit or delete a pre-existing test so the failing case is gone;
  2. write ``tests/conftest.py`` with ``collect_ignore = [...]`` so it never collects;
  3. add ``addopts = "--ignore=..."`` / ``testpaths = [...]`` to the project's pytest
     config so the suite silently shrinks (pytest still exits 0 — there is no
     collected-count check anywhere in the delivery path).

The coder has no write-scope restriction (only the tester is confined to ``tests/``), so all
three are open. This module snapshots the integrity-relevant surface from the PRISTINE clone
at run start; ``test_node`` re-checks it each iteration and a change becomes a first-class
gate reason (``tests_tampered``) that autonomous mode can never ship past (ADR-0036).

!! KNOWN LIMITS, both measured live 2026-08-06 — read before changing this module:
  · This detects that a baselined path CHANGED, not that it got WEAKER. A run deleted
    ``assert len(lines) == 2`` from a delivered test and **shipped**; a later run RESTORED it under
    explicit operator authorization and was **blocked**. The guard missed the dishonest edit and
    caught the honest one. Issue #66 — the answerable property is assertion count per test
    function, before vs after.
  · There is **no way for an operator to authorize a legitimate amendment**. A tamper verdict is
    terminal, so an item that deliberately CHANGES behaviour deadlocks against the test encoding
    the old behaviour (a five-line fix cost 3 runs / ~4M tokens and never shipped). Issue #65;
    direction in ADR-0087.

Design note — why we hash the pytest SECTION, not the whole config file: a legitimate run
adds a dependency to ``pyproject.toml``. Hashing the whole file would false-park it, which is
exactly the class of bug commit 217d735's regression corpus exists to prevent. So config
files contribute only their pytest-controlling section; a ``conftest.py`` contributes its
whole content (it *is* executable collection logic, and a legitimate run rarely edits one).
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from mosaera_core.pytestconfig import PytestNaming, resolve_naming
from mosaera_core.tools.repo import Workspace
from mosaera_core.validation import _read_root

# The one canonical "is this a test file" predicate. Three divergent regexes existed
# (quality.py, tools/repo.py, bench/harness.py) plus inline predicates in languages/python.py;
# this is the shared definition. Matches a bare basename OR a full repo-relative path.
_TEST_BASENAME = re.compile(r"^(test_.+|.+_test)\.py$", re.IGNORECASE)

# The ENUMERATION RULES that built a baseline, stamped beside it so a later check can tell whether
# the two are comparable. Bump on any change to WHICH paths `integrity_paths` returns.
#   "1" — `file_listing()`, capped at 300 sorted paths (pre-2026-08-22)
#   "2" — `security_listing()`, git-sourced and uncapped (1f710222)
#   "3" — classified by the TARGET'S OWN pytest naming (`python_files`/`testpaths`), not by
#         pytest's defaults, so a repo that renames its tests is protected at all
#
# Why this exists: `integrity_baseline` is snapshotted once and deliberately never refreshed (a
# re-baseline would absorb writes the coder already made). So when the enumerator widened 28 -> 249,
# every checkpoint written under "1" kept a 28-path baseline while the check enumerated 249, and the
# new-collection-control branch reported the difference as newly-created suppression vectors — on a
# PRISTINE tree, terminally. A baseline keyed on its inputs but not on its BUILDER; the same defect
# `OVERVIEW_RULES_VERSION` (tools/repo/diff.py) was introduced to fix, one layer over.
INTEGRITY_ENUMERATOR = "3"

_CONFTEST = "conftest.py"
# A section-bearing root config file -> the header that begins its pytest block. We hash only
# that section, so an unrelated edit (adding a dependency, a ruff setting) does not false-trip.
_CONFIG_SECTIONS: dict[str, str] = {
    "pyproject.toml": "[tool.pytest.ini_options]",
    "pytest.ini": "[pytest]",
    # The hidden variant pytest also reads. Absent from this table, a producer could CREATE one
    # mid-run to shrink the suite and it was not collection control, so nothing flagged it.
    ".pytest.ini": "[pytest]",
    "tox.ini": "[pytest]",
    "setup.cfg": "[tool:pytest]",
}


def is_test_file(rel: str) -> bool:
    """pytest's DEFAULT naming — ``test_*.py`` / ``*_test.py``. NOT the security predicate.

    A target may redefine collection via `python_files`, and on such a repo this answers False for
    every real test. The security sets go through `resolve_test_surface`, which reads the repo's own
    config; this is also the fallback that resolver uses when a target says nothing.

    IT REMAINS IN ~17 OTHER CALLERS, AND CALLING THEM ALL "non-security" WAS FALSE — a red team
    counted them. Four filtered a CONFIG-AWARE baseline with these DEFAULT names and have been
    moved to `baseline - is_collection_control`: `nodes_impl` (the mutation argv), `oraclecheck`
    (suite independence), `_proctor_authoring` (the weakening measure behind the tamper excuse) and
    `_modify_amendment` (amendment targets). `eligibility` keeps it DELIBERATELY — see the comment
    there; removing it re-opens a path that deletes a human's test. The rest (coverage ledger,
    destruction, nonuse, claim oracles) are scrutiny, where the default convention is the intended
    meaning."""
    return bool(_TEST_BASENAME.match(rel.rsplit("/", 1)[-1]))


def is_collection_control(rel: str) -> bool:
    """A conftest (anywhere) or a root config file that carries a pytest section — the files
    that decide WHICH tests run, as opposed to the test files themselves."""
    return rel.rsplit("/", 1)[-1] == _CONFTEST or rel in _CONFIG_SECTIONS


@dataclass(frozen=True)
class TestSurface:
    """The resolved test surface — the ONE origin the security sets are derived from.

    Four sets, not one, because the consumers genuinely disagree and the repo already knew it
    (ADR-0081: "a single predicate serving both [scrutiny and protection] is a smell"):

      C  ``collected``  — what pytest treats as a test file, by the target's own naming. It is
                          NOT exactly "what pytest collects": `addopts --ignore-glob` and
                          `norecursedirs` are unread, so it over-includes (51 files on this repo,
                          all under an ignored bench-cases glob). Over-inclusion is the SAFE
                          direction here and is deliberate, but the first version of this docstring
                          said "EXACT", which was false — the successor sourcing from
                          `--collect-only` is what would make it true.
      S  ``controls``   — conftest / root pytest config: what DECIDES which tests run. EXACT.
      P  protection     — what a producer may not edit. WIDE; over-inclusion is free.
      A  authorship     — what the engine created this run. EXACT; no safe side.

    They cannot be one set. `close_oracle_gap` needs `tests/check.py` IN (or its SHIP arm dies with
    "the tester authored no new test file"); the very same list becomes a pytest argv, where a
    `tests/fixtures/golden.json` makes pytest exit 4 — read, until recently, as "the mutation was
    caught". And putting fixtures under the content-hash tamper guard would brick a run on any
    fixture regeneration, because that verdict is terminal. One predicate cannot be both wide and
    exact, so the gap between two definitions of "the tests" produced two independent defects
    before anyone compared them.

    Note the derived rule that keeps downstream simple: the baseline is C-plus-S, and S is
    config-INDEPENDENT (a conftest is a conftest whatever `python_files` says), so any consumer
    holding only the baseline recovers C as ``baseline - is_collection_control``. No workspace
    needed, and no second place that has to know what `python_files` was.
    """

    naming: PytestNaming
    collected: frozenset[str]
    controls: frozenset[str]
    # Files that LOOK like tests under some other convention and are therefore NOT protected. Empty
    # on the overwhelmingly common case, which is the point — see `worth_telling_the_operator`.
    unprotected_candidates: frozenset[str] = frozenset()

    @property
    def worth_telling_the_operator(self) -> bool:
        """Does the inference actually leave something unguarded, or is it harmless?

        The first cut surfaced "the surface was inferred" on EVERY run with no pytest config — which
        is every greenfield target, i.e. 100% of runs on the live instance. Live validation caught
        it. A warning that fires always is wallpaper, and this is the other half of the standard
        (ISA-18.2) this arc already cited for the opposite failure: an operator who cannot see a
        suppressed alarm and an operator drowned in a constant one are both operators who cannot
        see. Deny-by-default is about the CONTROL failing closed, not about the prose volume.

        So: say it when the assumption could actually cost protection — there are test-shaped files
        the assumed convention does not cover — and stay quiet when it demonstrably costs nothing.
        A resolved surface never warrants it; drift always does, and rides its own note.
        """
        return bool(self.unprotected_candidates) and not self.naming.resolved

    @property
    def resolved(self) -> bool:
        """Did the TARGET tell us, or did we assume? Never inferred silently — see `naming.note`."""
        return self.naming.resolved


def resolve_test_surface(workspace: Workspace) -> TestSurface:
    """Read the repo's own pytest naming, then classify its committable paths once.

    `is_test_file` hard-codes pytest's DEFAULT `test_*.py`/`*_test.py`. A target that sets
    `python_files` had NO test baselined at all. Verified on a repo setting
    `python_files = ["check_*.py"]`: rewriting its acceptance test gave an EMPTY tamper result.
    That is `1f710222`'s headline claim still reproducing: that commit fixed which paths were
    ENUMERATED, not which of them COUNT.
    """
    naming = resolve_naming(
        lambda name: _read_root(workspace, name),
        lambda name: (workspace.root / name).is_file(),
    )
    listing = workspace.security_listing()
    # `testpaths` is deliberately NOT applied. It narrows where pytest looks WHEN GIVEN NO
    # ARGUMENTS — and ADR-0054 forbids us from synthesising path arguments at all, so we never use
    # it to build a command. Modelling it therefore buys nothing and costs protection: a literal
    # prefix match answered False for `.`, `./tests`, `tests/*` and absolute entries alike, and on
    # THIS repo (`testpaths = ["packages", "apps"]`) it dropped two real test files out of the
    # protected set. A test file that pytest would not collect by default is still a test someone
    # can run explicitly, and protecting it costs an honest park at worst.
    collected = {rel for rel in listing if naming.is_test_basename(rel)}
    controls = {rel for rel in listing if is_collection_control(rel)}
    # What a DIFFERENT convention would have caught: a `.py` file living under a tests directory
    # that our naming does not collect. Non-empty only when the repo really does name tests in a way
    # we are not protecting, which is exactly when the operator needs telling.
    candidates = {
        rel
        for rel in listing
        if rel.endswith(".py")
        and _under_a_tests_dir(rel)
        and rel not in collected
        and not is_collection_control(rel)
    }
    return TestSurface(naming, frozenset(collected), frozenset(controls), frozenset(candidates))


def _under_a_tests_dir(rel: str) -> bool:
    """Any path segment is exactly ``tests`` — `tests/x.py`, `packages/core/tests/x.py`."""
    return "tests" in rel.split("/")[:-1]


def protected_test_paths(workspace: Workspace) -> frozenset[str]:
    """The files a PRODUCER may not edit: every test file, plus every collection control.

    One origin for a set that six call sites each re-derived inline as
    ``{f for f in workspace.file_listing() if f.startswith("tests/")}`` — the second-origin shape
    this repo tracks, on a security control, six times over.

    That expression had TWO independent blind spots, and fixing only the famous one would have
    shipped a control that is still dead:

    1. ``file_listing`` caps at 300 globally-sorted paths and ``tests/`` sorts late, so the set was
       empty on any repo above the cap.
    2. ``startswith("tests/")`` requires a ROOT ``tests/`` directory. On Mosaera itself
       ``git ls-files | grep -c '^tests/'`` is **0** — the tests live at ``packages/core/tests/``.
       So on this repo, and on any src-layout or monorepo target, those six sets were
       unconditionally empty **whatever the cap did**.

    THREE terms, because it must be a superset of the expression it replaces — narrowing a security
    set while claiming to widen it is how this class propagates.

    PRECISELY: a superset at the PREDICATE level (brute-forced over 819 paths, zero counterexamples
    where the old `startswith("tests/")` matched and these three do not). NOT a superset at the SET
    level, because the SOURCE also changed: a test that is untracked-and-gitignored under root
    `tests/` was walked before and is not listed by git now. It cannot ship, and it cannot have come
    from the clone — but pytest does run it, so the gap is real if narrow. The first version of this
    docstring claimed a "genuine SUPERSET" without qualification; that was wrong at set level.

    * ``is_test_file`` — the repo's one canonical named predicate (basename ``test_*.py`` /
      ``*_test.py``, **at any depth**). This is the term that fixes blind spot 2.
    * ``is_collection_control`` — a conftest decides WHICH tests run, so a producer editing one is
      exactly the vector the guard exists to stop.
    * ``_under_a_tests_dir`` — anything inside a directory named ``tests``, test-named or not.
      Dropping this term narrowed the set: ``tests/check.py`` matched ``startswith("tests/")`` and
      none of the basename predicates, and ``close_oracle_gap`` uses this set to recognise what the
      tester AUTHORED. Losing it made a legitimately authored helper invisible and the SHIP arm
      answered ``"the tester authored no new test file"``. Caught by `test_disposition.py`, which
      exists because a red team found that exact file shape.
    """
    surface = resolve_test_surface(workspace)
    return frozenset(
        surface.collected
        | surface.controls
        | {rel for rel in workspace.security_listing() if _under_a_tests_dir(rel)}
    )


def integrity_paths(workspace: Workspace) -> list[str]:
    """The paths whose integrity we baseline: every pre-existing test file, every
    ``conftest.py``, and every root config file that carries a pytest section. Sorted,
    de-duplicated, repo-relative.

    Reads ``security_listing``, NOT ``file_listing``. It read the capped presentation listing until
    2026-08-22, so on any repo above 300 sorted paths this returned ``[]`` and the whole tamper
    guard was silent — verified on a 401-file repo, where the producer rewrote its own acceptance
    test to ``assert True`` and ``tampered_integrity`` returned ``[]``. ``security_listing`` RAISES
    rather than degrading; that propagates here on purpose, because every value this function could
    return on failure reads downstream as "nothing is protected"."""
    surface = resolve_test_surface(workspace)
    return sorted(surface.collected | surface.controls)


def _pytest_section(content: str, header: str) -> str:
    """The lines from ``header`` to the next top-level section header, or ``""`` if the header
    is absent. Lines are stripped, so reindentation alone is not treated as a change."""
    out: list[str] = []
    capturing = False
    for line in content.splitlines():
        stripped = line.strip()
        if not capturing:
            if stripped == header:
                capturing = True
                out.append(stripped)
            continue
        # A new top-level "[...]" header ends the section — but keep TOML sub-tables that
        # extend this header (e.g. "[tool.pytest.ini_options.foo]").
        if (
            stripped.startswith("[")
            and stripped.endswith("]")
            and not stripped.startswith(header[:-1])
        ):
            break
        out.append(stripped)
    return "\n".join(out)


def _integrity_content(workspace: Workspace, rel: str) -> str:
    """The bytes-that-matter for ``rel``: the whole file for a test / conftest, or just the
    pytest section for a config file. Missing / unreadable → ``""`` (so deletion is a change)."""
    path = workspace.root / rel
    try:
        if path.is_symlink():
            # GIT'S OWN SEMANTICS: a symlink's content is its TARGET STRING (what git stores in the
            # 120000 link blob), never the dereferenced bytes. `committable_paths` does not filter
            # symlinks the way `file_listing` deliberately did, so without this a source repo
            # tracking `tests/test_x.py -> /etc/passwd` would have it read HOST-SIDE and carried
            # into a model prompt and the operator's report. Skipping instead would be worse than
            # useless: `""` reads as deleted, so every symlinked test would park the run forever.
            # Hashing the target also means repointing the link, or swapping a real test for a
            # link, correctly trips the guard.
            return os.readlink(path)
        # Belt-and-braces for the case `is_symlink()` on the leaf cannot see — a symlinked PARENT
        # directory. `resolve` raises if the path escapes the clone.
        workspace.resolve(rel)
        raw = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
    header = _CONFIG_SECTIONS.get(rel)
    return raw if header is None else _pytest_section(raw, header)


def integrity_text(workspace: Workspace, rel: str) -> str:
    """``rel``'s integrity-relevant text, read with containment (see ``_integrity_content``).

    Public so callers that need the CONTENT of a protected file — `bench.operator.oracle_texts` —
    get the symlink and path-escape handling for free instead of re-deriving a raw `read_text`,
    which is how the same hole ended up in three places.
    """
    return _integrity_content(workspace, rel)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def integrity_hash(workspace: Workspace, rel: str) -> str:
    """The tamper-guard hash of ``rel``'s integrity-relevant content — the SAME hash space as
    ``integrity_baseline`` (newline-normalized text for a test/conftest, the pytest section for a
    config file). A caller recording a SANCTIONED edit to a baselined path (the Proctor's up-front
    repair, #54) MUST hash through this, so the excuse compares apples-to-apples with the guard; a
    raw-bytes hash would land in the wrong space and false-park on CRLF (the gap_fill lesson)."""
    return _hash(_integrity_content(workspace, rel))


def integrity_baseline(workspace: Workspace) -> dict[str, str]:
    """Snapshot the integrity surface: path -> hash of its integrity-relevant content. Take
    this from the PRISTINE clone, once, at run start (before the coder's first write)."""
    return {rel: _hash(_integrity_content(workspace, rel)) for rel in integrity_paths(workspace)}


def tampered_integrity(
    workspace: Workspace,
    baseline: Mapping[str, str],
    *,
    ignore: Iterable[str] = (),
    proctor_edits: Mapping[str, str] | None = None,
    operator_edits: Mapping[str, str] | None = None,
    baseline_complete: bool = True,
) -> list[str]:
    """Integrity-relevant paths that changed since ``baseline`` — a pre-existing test
    edited/deleted, a conftest changed, a pytest section altered, or a NEW collection-control
    file (conftest / pytest config) created after run start (a fresh ``collect_ignore`` is a
    suppression vector even though it touches no baselined path).

    ``ignore`` excludes legitimately-INTRODUCED paths — chiefly the tester's authored tests,
    which are created AFTER the baseline is taken and are already governed by their own
    protected-path guard. Without this, an enabled tester would false-trip on its own files.

    A path in ``baseline`` is pre-existing by definition, so ``ignore`` can never excuse it:
    the tester authoring at a path that COLLIDES with a pre-existing baselined test (overwriting
    it) puts that path in ``authored_tests`` → the caller passes it in ``ignore`` → without this
    subtraction the overwrite of a protected test would be silently excused (the very
    manufacture-a-green-suite move the guard exists to stop). ``ignore`` applies to newly-added
    paths only.

    ``proctor_edits`` (#54, ADR-0058) is the ONE sanctioned way a BASELINED path may change: the
    Proctor's up-front, coder-blind repair of a pre-existing test. It maps path -> integrity_hash
    of the Proctor's post-edit content (recorded in ``author_tests_node``, this exact hash space). A
    baselined path is excused ONLY if its on-disk content hashes to EITHER the pristine baseline OR
    the Proctor's recorded hash — any OTHER content (a later coder re-weakening, or a hash the
    Proctor never sanctioned) still trips. So the excuse is content-pinned to the Proctor's exact
    edit, never a blanket "this path may change"; the pristine ``baseline`` stays untouched
    (immutable). A non-hex sentinel can't slip: ``proctor_edits.get(rel)`` is ``None`` for unlisted
    paths and a hash never equals ``None``. And an EMPTY on-disk integrity content (a deleted OR
    emptied test) is NEVER excused, even by a sanctioned ``hash("")`` — emptying drops a requirement
    wholesale, exactly like deletion (red-team #54 FN1); this is enforced at the guard below.

    ``operator_edits`` (F63, #65) is the SECOND sanctioned source, in exactly the same hash space
    and under exactly the same rules. It carries writes a HUMAN approved at the write gate, where
    the operator saw the diff and the resulting content was already known — so the approval can be
    recorded as a fact rather than staying prose.

    Why it exists: an item whose PURPOSE is to change behaviour necessarily invalidates the test
    encoding the old behaviour. That test is baselined, editing it trips this guard, and a tamper
    verdict is terminal — so the work deadlocks. Measured 2026-08-06: a five-line deletion took
    three runs and ~4M tokens and never shipped. The operator authorized the amendment explicitly
    at the escalation gate and the authorization went NOWHERE, because it lived in a feedback
    string and this function never saw it.

    The load-bearing constraint is at the recording site, not here: only a decision whose actor is
    ``human`` may sanction. An autonomous auto-approve that could sanction its own writes would
    retire ADR-0036 silently.

    **An operator sanction NEVER applies to a collection-control file** (conftest, a pytest config
    section) — red-team of this change, round 2. Human authority extends to amending a test's
    CONTENT, not to removing tests from the run. A ``collect_ignore`` drops requirements wholesale
    exactly as emptying a test does (the FN1 rule), and it is *worse* to review: the effect is
    invisible in any test file, so an operator can approve a small-looking config diff that
    silently shrinks the suite while pytest still exits 0.
    """
    skip = set(ignore) - set(baseline)
    # Both sources share one space and one rule set. An operator sanction is not a stronger excuse
    # than the Proctor's — it is the same content-pinned excuse from a different authority.
    sanctioned = dict(proctor_edits or {})
    # Operator sanctions apply to TEST CONTENT only — never to what gets collected (see above).
    sanctioned.update(
        {rel: h for rel, h in (operator_edits or {}).items() if not is_collection_control(rel)}
    )
    empty = _hash("")  # integrity hash of a deleted OR emptied file (both → "" content)
    out: list[str] = []
    for rel, digest in baseline.items():
        if rel in skip:
            continue
        current = _hash(_integrity_content(workspace, rel))
        if current == digest:
            continue  # unchanged
        # A proctor_edits excuse is content-pinned, but it can NEVER sanction an EMPTY/DELETED
        # baselined test: emptying a test (write_file "") and deleting it both yield "" content →
        # the same hash("") , which would otherwise let a sanctioned hash("") launder a dropped
        # requirement (red-team #54 FN1). So an empty on-disk integrity content is ALWAYS tampering,
        # regardless of the excuse. A non-empty change is excused only by an exact sanctioned match.
        if current == empty or current != sanctioned.get(rel):
            out.append(rel)
    if not baseline_complete:
        # The baseline was built by a DIFFERENT enumerator, so "enumerated now but absent from the
        # baseline" no longer implies "created after run start" — it mostly means "the enumerator
        # widened underneath a snapshot we are right not to refresh". Running this branch anyway
        # convicts a pristine tree, and `tests_tampered` is terminal.
        #
        # Branch A above is UNAFFECTED and still runs: it iterates the baseline itself, never the
        # enumerator, so every path the old baseline does cover is still content-checked. What is
        # lost is only "a new collection control appeared", and only for runs already in flight
        # across the upgrade. `tamper_verdict` records the suppression so the operator sees the
        # narrowed coverage instead of either a false accusation or silence.
        return sorted(set(out))
    baselined = set(baseline)
    # A collection-control file created after run start is a suppression vector — but only if it
    # actually controls collection. `_integrity_content` is the pytest SECTION for a config file
    # ("" when the header is absent) and the whole file for a conftest, so an empty result means
    # the file decides nothing about which tests run and cannot hide one. Flagging it anyway
    # false-parks a legitimate deliverable: measured 2026-08-06, the coder scaffolded
    # `pyproject.toml` — acceptance criterion #1 of the slice — the suite passed 7/7, and delivery
    # was blocked on `tests_tampered`. That made every Python project whose first slice creates a
    # pyproject undeliverable. This is the same false-park class the baselined path already guards
    # by hashing only the pytest section (217d735); the guard simply never reached NEW files.
    # `.strip()` because a whitespace-only conftest controls collection exactly as much as an
    # empty one does — nothing (red-team of this change, 1 finding, fixed here).
    out += [
        rel
        for rel in integrity_paths(workspace)
        if rel not in baselined
        and rel not in skip
        and is_collection_control(rel)
        and _integrity_content(workspace, rel).strip() != ""
    ]
    return sorted(set(out))


__all__ = [
    "INTEGRITY_ENUMERATOR",
    "TestSurface",
    "integrity_baseline",
    "integrity_hash",
    "integrity_paths",
    "integrity_text",
    "is_collection_control",
    "is_test_file",
    "protected_test_paths",
    "resolve_test_surface",
    "tampered_integrity",
]
