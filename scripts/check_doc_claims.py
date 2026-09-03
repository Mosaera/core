#!/usr/bin/env python3
"""Doc-claims guard — a documented CLAIM that another fact in this repo contradicts.

Why this exists. On 2026-08-06 two findings turned out to be REDISCOVERIES of knowledge already
written down here:

  * F62 re-derived an allowlist defect measured the previous day AND quoted at length in the
    roadmap's Current focus — then a feature was built on that same broken allowlist.
  * F58 rediscovered F30 from scratch, one day later.

The research that followed (docs/research/documentation-retrievability-and-staleness-2026-08-06.md)
found one durable principle: **a status a human types is structurally unfixable; a status that is
DERIVED cannot go stale.** Ericsson's study of 318 documentation defects put 59% in the
automatable bucket. So this guard never asks whether prose is *true* — it only reports where two
facts already in the repo DISAGREE.

Every check below is a contradiction between two existing artifacts. No NLP, no judgement, no new
metadata to maintain, nothing a reviewer can rubber-stamp.

Deliberately NOT checked, so the next person does not add them:
  * prose accuracy, and whether a doc's rationale still holds — human review only;
  * freshness TTL / `last-reviewed` dates — a date a human retypes is a NAG, not a gate, and
    a contradiction check is strictly better because it compares two facts;
  * code-comment/prose semantic consistency — research-grade only (Deep-JIT, CUP, SEOCD), with
    false-positive rates that would exceed the true positives we care about.

Absent fields are NOT failures. ADR header fill is genuinely uneven (`Implementation`,
`Date accepted`, `Supersedes` and `Review trigger` appear in a minority of ADRs, and header spelling
varies — 89 use `- Status:`, 12 use `- **Status:**`). Only an EXPLICIT claim can contradict —
otherwise the guard would fail
on day one and be switched off, which is how executable documentation dies (Gojko: 29% abandonment).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = ROOT / "docs" / "adr"
ADR_INDEX = ADR_DIR / "README.md"

# Where an ADR being CITED counts as evidence that it is in force. Source trees only: a citation
# in docs/ is just cross-referencing, but a citation in shipped code means the decision governs
# something real.
SOURCE_DIRS = ("packages", "apps", "scripts")
SOURCE_SUFFIXES = (".py", ".ts", ".tsx")
_SKIP_PARTS = ("__pycache__", "node_modules", ".venv", "dist", "migrations")

_ADR_ID_RE = re.compile(r"ADR-(\d{4})")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
# `- Status: ...` / `- Implementation: ...` at the top of an ADR.
_FIELD_RE = r"^[-*]\s*{field}\s*:\s*(.+)$"
# An index row: | [ADR-0001](file.md) | Decision | status | subsystem |
_INDEX_ROW_RE = re.compile(r"^\|\s*\[ADR-(\d{4})\]\([^)]+\)\s*\|[^|]*\|\s*([^|]+?)\s*\|")

# ADRs whose status line is prose rather than an enum, so the index-sync check cannot compare it.
# SHRINK-ONLY: fixing an ADR's header means deleting its entry here. Never add without cause.
PROSE_STATUS_GRANDFATHERED: frozenset[str] = frozenset({"0077"})

# ADR ids that were ALLOCATED and then never became decisions. The index's own history prose
# mentions them on purpose ("0030 tombstone", "0037 never used"), so a reference is not a dangling
# pointer. Numbers are never reused, so this list only ever grows by a deliberate act.
TOMBSTONED_ADRS: frozenset[str] = frozenset({"0030", "0037"})

# ADRs cited by source code as DIRECTION rather than as an in-force decision — e.g. a comment
# saying a proposed posture "would gate on this shape". Such a citation is not evidence the
# decision is built, so it must not trip the cited-but-unbuilt check.
#
# SHRINK-ONLY, and that is the whole point: when one of these is actually built, its
# `Implementation:` stops saying not-started, the guard reports the entry as stale, and it must be
# deleted. An ADR that sits here for a long time is a direction nobody is building — visible, which
# is better than invisible.
# 0087 removed 2026-08-06: its §5 was BUILT, so the ratchet demanded it — the first
# real exercise of the shrink-only half.
# 0084 removed 2026-08-18: §3 shipped (`graph/_design_cache.py`, migration 0023) and the header
# was corrected from not-started to partial, so the ratchet demanded it. Follow-ups (a) and (c)
# remain open, but the ADR no longer claims to be unbuilt, which is what this list tracks.
DIRECTION_CITED: frozenset[str] = frozenset({"0086"})


def _field(text: str, field: str) -> str | None:
    """The value of an ADR header field, or None when the ADR makes no such claim."""
    m = re.search(_FIELD_RE.format(field=field), text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _adr_files() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in sorted(ADR_DIR.glob("ADR-*.md")):
        m = _ADR_ID_RE.match(p.name)
        if m and m.group(1) != "0000":  # the template is not a decision
            out[m.group(1)] = p
        elif m:
            continue
    return out


def _source_files() -> list[Path]:
    files: list[Path] = []
    for d in SOURCE_DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.suffix not in SOURCE_SUFFIXES or not p.is_file():
                continue
            if any(part in _SKIP_PARTS for part in p.parts):
                continue
            files.append(p)
    return files


def _claims_unbuilt(text: str) -> str | None:
    """The explicit claim that this decision is not in force, or None.

    `Status: proposed` alone is NOT enough — a proposed ADR may legitimately be cited by the code
    it is proposed about. It is `Implementation: not-started` that contradicts a citation.
    """
    impl = _field(text, "Implementation")
    if impl and impl.lower().startswith("not-started"):
        return f"Implementation: {impl}"
    return None


def check_cited_but_unbuilt(adrs: dict[str, Path]) -> list[str]:
    """An ADR cited by shipped code must not claim it is unbuilt.

    This is the check that catches the motivating case: ADR-0085's freeze governed the F52
    assertion-floor fix while its header still read `Implementation: not-started`.
    """
    fails: list[str] = []
    cited: dict[str, Path] = {}
    for src in _source_files():
        try:
            body = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _ADR_ID_RE.finditer(body):
            cited.setdefault(m.group(1), src)
    for adr_id, where in sorted(cited.items()):
        path = adrs.get(adr_id)
        if path is None:
            continue  # dangling refs are reported by check_references
        if adr_id in DIRECTION_CITED:
            continue  # cited as direction, not as an in-force decision
        claim = _claims_unbuilt(path.read_text(encoding="utf-8", errors="replace"))
        if claim:
            rel = where.relative_to(ROOT)
            fails.append(
                f"{path.relative_to(ROOT)}: claims '{claim}' but ADR-{adr_id} is cited by {rel}"
            )

    # The shrink-only half: an entry that no longer claims to be unbuilt has been BUILT, so the
    # grandfathering is stale and must be removed. Without this the list is decorative.
    for adr_id in sorted(DIRECTION_CITED):
        path = adrs.get(adr_id)
        if path is None:
            fails.append(f"DIRECTION_CITED lists ADR-{adr_id}, which does not exist — remove it")
        elif not _claims_unbuilt(path.read_text(encoding="utf-8", errors="replace")):
            fails.append(
                f"DIRECTION_CITED lists ADR-{adr_id}, which no longer claims to be unbuilt "
                f"— it was built; remove it from the list"
            )
    return fails


def check_references(adrs: dict[str, Path]) -> list[str]:
    """Every ADR-NNNN mentioned in docs/ resolves to a real ADR."""
    fails: list[str] = []
    for md in sorted((ROOT / "docs").rglob("*.md")):
        text = _FENCE_RE.sub("", md.read_text(encoding="utf-8", errors="replace"))
        for line_no, line in enumerate(text.splitlines(), 1):
            for m in _ADR_ID_RE.finditer(line):
                adr_id = m.group(1)
                if adr_id == "0000" or adr_id in adrs or adr_id in TOMBSTONED_ADRS:
                    continue
                fails.append(f"{md.relative_to(ROOT)}:{line_no} -> ADR-{adr_id} does not exist")
    return fails


def check_index_sync(adrs: dict[str, Path]) -> list[str]:
    """The hand-maintained index agrees with disk, in BOTH directions, including status."""
    fails: list[str] = []
    rows: dict[str, str] = {}
    for line in ADR_INDEX.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _INDEX_ROW_RE.match(line.strip())
        if m:
            rows[m.group(1)] = m.group(2).strip()

    for adr_id in sorted(set(adrs) - set(rows)):
        fails.append(f"docs/adr/README.md: ADR-{adr_id} exists on disk but has no index row")
    for adr_id in sorted(set(rows) - set(adrs)):
        fails.append(f"docs/adr/README.md: indexes ADR-{adr_id}, which does not exist")

    for adr_id in sorted(set(rows) & set(adrs)):
        if adr_id in PROSE_STATUS_GRANDFATHERED:
            continue
        own = _field(adrs[adr_id].read_text(encoding="utf-8", errors="replace"), "Status")
        if not own:
            continue  # no claim made
        # Tolerant containment, not equality: the index is a one-word summary while the ADR may
        # elaborate ("**SUPERSEDED / REVERTED** — measured net-null"), and both are true. Only a
        # row whose word appears NOWHERE in the ADR's own status is a real disagreement.
        own_words = set(re.findall(r"[a-z]+", own.lower()))
        row_word = re.sub(r"[^a-z]", "", rows[adr_id].split()[0].lower()) if rows[adr_id] else ""
        if row_word and own_words and row_word not in own_words:
            fails.append(
                f"docs/adr/README.md: ADR-{adr_id} indexed '{row_word}' but the ADR says '{own}'"
            )
    return fails


def check_supersession(adrs: dict[str, Path]) -> list[str]:
    """Supersession must be bidirectional: a one-way link means one side is lying.

    The research names this the highest-yield ADR lint that almost nobody implements.
    """
    fails: list[str] = []
    superseded_by: dict[str, set[str]] = {}
    supersedes: dict[str, set[str]] = {}
    for adr_id, path in adrs.items():
        raw = _field(
            path.read_text(encoding="utf-8", errors="replace"), "Supersedes / Superseded by"
        )
        if not raw:
            continue
        low = raw.lower()
        # Only act on an unambiguous single-direction statement; mixed prose is left alone.
        ids = {m.group(1) for m in _ADR_ID_RE.finditer(raw)}
        if not ids:
            continue
        if "superseded by" in low and "supersedes" not in low.replace("superseded by", ""):
            superseded_by[adr_id] = ids
        elif "supersedes" in low and "superseded by" not in low:
            supersedes[adr_id] = ids

    for adr_id, targets in sorted(superseded_by.items()):
        for target in sorted(targets):
            if target in adrs and adr_id not in supersedes.get(target, set()):
                fails.append(
                    f"docs/adr/ADR-{adr_id}: says superseded by ADR-{target}, "
                    f"but ADR-{target} does not say it supersedes ADR-{adr_id}"
                )
    return fails


def check_make_lint_contract() -> list[str]:
    """CLAUDE.md's description of `make lint` must match the Makefile's `lint:` prerequisites.

    The documented command contract is exactly the kind of hand-typed claim that drifts: on
    2026-08-06 CLAUDE.md described three guards while the Makefile ran four, and
    check_control_liveness.py's own docstring said it was "wired into nothing" after it was wired.
    """
    fails: list[str] = []
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^lint:([^\n]*)$", makefile, re.MULTILINE)
    if not m:
        return [
            "Makefile: no `lint:` target found — the doc-claims guard cannot verify the contract"
        ]
    targets = [t for t in m.group(1).split() if t.startswith("check-")]

    # Each `check-<x>` target runs one script; collect the script names it actually invokes.
    scripts: set[str] = set()
    for target in targets:
        body = re.search(rf"^{re.escape(target)}:.*?(?=^\w|\Z)", makefile, re.MULTILINE | re.DOTALL)
        if body:
            scripts.update(re.findall(r"(check_\w+\.py)", body.group(0)))

    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    line = re.search(r"^make lint\s+#(.+)$", claude, re.MULTILINE)
    if not line:
        return ["CLAUDE.md: no `make lint` command-contract line found"]
    documented = set(re.findall(r"(check_\w+\.py)", line.group(1)))

    for missing in sorted(scripts - documented):
        fails.append(f"CLAUDE.md: `make lint` runs {missing} but the documented contract omits it")
    for extra in sorted(documented - scripts):
        fails.append(
            f"CLAUDE.md: documents {extra} in `make lint`, but the Makefile does not run it"
        )
    return fails


FINDING_LOG = ROOT / "docs" / "engineering-history" / "ledgercli-friction-log-2026-08-05.md"
ROADMAP = ROOT / "docs" / "roadmap.md"

# A finding heading: `## F62 · Title — HIGH · OPEN (found ...)`.
_FINDING_RE = re.compile(r"^#{2,3}\s+(F\d+)\s+·\s+(.*)$", re.MULTILINE)
# A roadmap arc/prereq/debt heading naming its issue: `**[arc] Title — `#64`**`.
_ARC_RE = re.compile(r"^\*\*\[(?:arc|prereq|debt)\][^\n]*?`#(\d+)`")
_STATUS_BULLET_RE = re.compile(r"^- \*\*Status:\*\*")
_SEVERITY_RE = re.compile(r"\b(CRITICAL|HIGH|MED|LOW)\b")


def _findings() -> list[tuple[str, str, str]]:
    """(id, heading-remainder, body) for every finding in the live log."""
    text = FINDING_LOG.read_text(encoding="utf-8")
    parts = _FINDING_RE.split(text)
    out: list[tuple[str, str, str]] = []
    for i in range(1, len(parts), 3):
        out.append((parts[i], parts[i + 1], parts[i + 2]))
    return out


def _is_open(heading: str) -> bool:
    """OPEN, and not settled.

    A heading may be qualified — F48 reads `~~HIGH~~ **FIXED 2026-08-06 · residual OPEN (LOW)**`.
    FIXED/WITHDRAWN wins over a later "residual OPEN" clause, or the guard fails on honest records
    and gets switched off.
    """
    if re.search(r"\b(FIXED|WITHDRAWN)\b", heading):
        return False
    return "OPEN" in heading


def _severity(heading: str) -> str | None:
    """The claimed severity, ignoring anything struck through (`~~HIGH~~` is a former severity)."""
    m = _SEVERITY_RE.search(re.sub(r"~~.*?~~", "", heading))
    return m.group(1) if m else None


def check_findings_tracked() -> list[str]:
    """An OPEN HIGH/CRITICAL finding must name the issue that tracks it.

    Findings accumulated to 47 open with ZERO tracked as issues, and the cost was measured: F62
    re-derived a defect documented the previous day, F58 rediscovered F30. A log nobody reads at
    session start is write-only. This turns "file an issue" from discipline into a gate.

    Severity may be revised down honestly — that is a judgement, recorded in the heading, and it is
    the only other way out.
    """
    fails: list[str] = []
    for fid, heading, body in _findings():
        if not _is_open(heading) or _severity(heading) not in ("HIGH", "CRITICAL"):
            continue
        # Both forms count: `Tracked as [issue #71](<tracker-url>)` in this repository, and
        # the de-linked `Tracked as issue #71` the public distribution build produces (the
        # tracker is not reachable from there). The requirement is unchanged — an open
        # HIGH/CRITICAL finding must NAME the issue that tracks it.
        if not re.search(r"Tracked as \[?issue", body[:1200]):
            fails.append(
                f"{FINDING_LOG.relative_to(ROOT)}: {fid} is OPEN/{_severity(heading)} with no "
                f"tracking issue — file one, or revise the severity honestly"
            )
    return fails


def check_roadmap_claims() -> list[str]:
    """A roadmap arc marked DONE must acknowledge any OPEN finding filed against it.

    The motivating case: `#64` read **Status: DONE** while F62 was open against the ESCALATE arm
    that arc produced — a reader concluded the arm worked. Rule: if an OPEN finding names arc `#N`
    and `#N` is DONE, the arc entry must reference that finding's tracking issue.

    HONEST LIMIT: this catches DRIFT, not authoring error. When `#64` was marked DONE the defect
    had not been found and no local check could have known. What it prevents is the claim
    PERSISTING once a contradicting finding exists.
    """
    fails: list[str] = []
    lines = ROADMAP.read_text(encoding="utf-8").split("\n")
    arcs: dict[str, tuple[list[str], list[str]]] = {}  # issue -> (status-lines, body-lines)
    cur: str | None = None
    for line in lines:
        m = _ARC_RE.match(line)
        if m:
            cur = m.group(1)
            arcs[cur] = ([], [])
        elif cur is not None:
            if line.startswith("**["):
                cur = None
                continue
            status, body = arcs[cur]
            if _STATUS_BULLET_RE.match(line) and not status:
                status.append(line)
            body.append(line)

    done = {k for k, (status, _) in arcs.items() if any("DONE" in ln for ln in status)}
    for fid, heading, body in _findings():
        if not _is_open(heading):
            continue
        head = body[:1500]
        tracked = re.search(r"Tracked as \[?issue #(\d+)", head)
        for arc in sorted({m.group(1) for m in re.finditer(r"#(\d{1,3})\b", head)} & done):
            entry = "\n".join(arcs[arc][1])
            if tracked and re.search(rf"#{tracked.group(1)}\b", entry):
                continue  # the arc acknowledges it
            fails.append(
                f"docs/roadmap.md: arc #{arc} is marked DONE but {fid} is OPEN against it "
                f"— the entry must reference "
                f"{'issue #' + tracked.group(1) if tracked else 'the tracking issue'}"
            )
    return fails


def main() -> int:
    adrs = _adr_files()
    groups = [
        ("cited by code but claims to be unbuilt", check_cited_but_unbuilt(adrs)),
        ("references an ADR that does not exist", check_references(adrs)),
        ("index disagrees with disk", check_index_sync(adrs)),
        ("one-way supersession", check_supersession(adrs)),
        ("documented `make lint` contract is wrong", check_make_lint_contract()),
        ("a DONE arc has an OPEN finding against it", check_roadmap_claims()),
        ("an OPEN HIGH/CRITICAL finding is untracked", check_findings_tracked()),
    ]
    total = sum(len(f) for _, f in groups)
    if total:
        print(
            "Doc-claims guard FAILED — a documented claim contradicts another fact in this repo:\n"
        )
        for label, fails in groups:
            if not fails:
                continue
            print(f"  {label}:")
            for f in fails:
                print(f"    {f}")
            print()
        print(f"{total} contradiction(s).")
        return 1

    stale = PROSE_STATUS_GRANDFATHERED - set(adrs)
    if stale:
        print(f"NOTE: remove from PROSE_STATUS_GRANDFATHERED (no such ADR): {sorted(stale)}")
    print(f"Doc-claims guard OK: {len(adrs)} ADRs, no contradictions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
