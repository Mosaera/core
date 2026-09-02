# ADR-0076: Independent security gate — a scan that could not run is UNVERIFIED, never CLEAN

- Status: accepted (merged 2026-07-23; **red-team DONE — 2 rounds, pre-merge**, see §Red-team; trust-boundary file-domain)
- Date: 2026-07-23
- Owners: @Ashura
- Related issue: #83 (NS-2 governance — security control-point arc, MR-1)
- Related threat model: TM-0001

## Context

The 2026-07-23 firm research (DORA / NIST SSDF / Google SRE / NIST AI RMF) validated Mosaera's
evidence-engine moat and flagged **control-point independence** — especially security — as the first
real gap. The owner picked the security control point as the next lever, with the DNA constraint
"control points, not headcount": a deterministic gate + evidence adapter, **not** a chatty security
role.

The delivery gate already carries a `security_findings` reason, but the security signal is a
**false-green**:

- `scan_node` early-returns `{"findings": [], "findings_text": "No security findings."}` when no
  scanner or scan sandbox is configured — **indistinguishable in RunState from a real clean scan**.
  The bench harness builds the graph with no scanners, so *every* benchmark run shipped through this
  path; the graph-integration "happy path" test delivered through it too.
- `Scanner.scan` ignores the sandbox exit code, so a missing/crashed scanner parses to `[]` = "clean"
  even when it ran (or didn't).
- `evaluate_gate` has **no signal for "the scan could not run"** and no severity concept.

"We did not look" was treated identically to "we looked and it's clean" — the same class of
false-green caught in the #40 map store. Notably, `recon/security.py` already solved exactly this for
the durable map (exit-code classification + a positive well-formed-report check → tri-state
`unavailable`/`findings`/`clean`), and its own docstring named the run-gate `scan.py` path as the
defect still to fix.

## Decision

Make the security control point real, as a **monotonic** change — it only ever *adds* a deny.

1. **Tri-state `security_status`** ∈ `clean | findings | unavailable | disabled`, emitted by
   `scan_node` into RunState. `unavailable` = a scan was EXPECTED this run but produced no verdict
   (no scan sandbox, or a missing/crashed scanner). `disabled` = the operator opted out
   (`scan_enabled=False`).
2. **A new deny-by-default gate reason `security_unverified`**, mirroring `validation_unavailable`:
   `security_status == "unavailable"` → `evaluate_gate` appends `security_unverified` → the run parks
   in every mode. A distinct reason, so it can never satisfy the reviewer-silence backstop
   (`core != ["reviewer_unknown"]`). `clean` / `findings` / `disabled` add no reason (a real finding
   still parks via the unchanged `security_findings`).
3. **Conditioned on the existing `scan_enabled` knob — NO new posture.** The "was security expected?"
   decision lives in `scan_node`: an explicit opt-out reads as `disabled` (no deny); `scan_enabled`
   with no scan backend reads as `unavailable` (parks). The three callers (`cli`, `factory`, bench)
   fold their per-run opt-out (`--no-scan`, `req.scan`, bench-has-no-scan-container) into
   `scan_enabled` via `dataclasses.replace`, so no hot-file (`build_graph`/`context`) signature
   changes.
4. **Severity carried as DATA only.** `Finding` gains a trailing `severity` (semgrep ERROR/WARNING/
   INFO → high/medium/low, unknown → medium; gitleaks secrets → critical). It feeds the reviewer
   prompt and report; the gate does **not** tier on it in this MR (that is deferred, posture-gated).
5. **One shared classifier.** `run_one` / `emitted_report` / `run_scan` are lifted into `tools/scan.py`
   and shared by BOTH the run gate and recon (recon re-exports under its old private names) — the two
   trust surfaces now agree on "did the scan actually run". A zero-finding result is trusted as CLEAN
   only if the scanner produced a COMPLETE report of its own shape (`Scanner.reported_completely`) — a
   semgrep run with a non-empty `errors` array (a target file it could not parse) is a *partial* scan
   → `unavailable`, never clean-by-omission (red-team A). Any findings a partial scan did yield still
   ride along, but the run parks.

Monotonicity is guaranteed by the `security_status="clean"` default on `evaluate_gate`: every existing
caller and the 24-row decision table are byte-identical.

## Options considered

- **Posture-scale the veto now (Free advisory / Business+Regulated blocking).** Rejected for MR-1:
  charter posture (`free/business/regulated`) is a real persisted enum but has **zero enforcement
  seam** today; building the first ADR-0046 enforcement consumer is a governance milestone of its own.
  Deferred (see below); the `scan_enabled` conditioning composes with it later.
- **Severity-based gate tiering now** (low/info non-blocking). Rejected: it would *loosen* the gate
  (a finding that parks today would ship) — a non-monotonic change to a trust boundary, harder to
  red-team. Severity ships as data; tiering is a later, deliberate, posture-gated change.
- **A new `build_graph`/`RunContext` param for "security required".** Rejected: it edits two hot files
  for a distinction the existing `scan_enabled` knob already expresses once the callers fold it in.
- **Add a `GateDecision.security_status` field.** Rejected: the reason rides in `reasons[]`; a new
  field would churn the serialized payload + round-trip test for no gain.
- **Trivy / SCA in this MR.** Rejected: it touches `infra/docker/scan.Dockerfile` and
  `packages/policies/allowlist.py`, both CODEOWNERS-gated — a separate owner-approved MR.

## Security implications

This is a **tightening** of the ship invariant, in the deny-by-default direction: a run that could
not verify security no longer ships unattended (it parks for a human). It closes a false-green over
the delivered product's security. The shared `run_one` classifier means the run gate and the durable
map can no longer diverge on missing-vs-clean. No secret material is added to any artifact (the
`Finding` fields are unchanged except severity; recon's secret-free `_observe` is untouched). Trust
boundary: `packages/policies/gate.py` (CODEOWNERS). **RED-TEAM-REQUIRED** before the class is trusted.

## Operational implications

**Intended behavior change:** a default-config run with `scan_enabled=True` but no Docker scan backend
now PARKS on `security_unverified` (previously it shipped as if clean). The escape hatch is an explicit
opt-out — `scan_enabled=False` / `--no-scan` — which reads as `disabled` and does not park. The bench
harness sets `scan_enabled=False` (it provisions no scan container), so the reliability baseline is
undisturbed. A flaky scan sandbox that crashes → `unavailable` → park (correct-but-stricter; no retry
in MR-1). No migration, no new knob.

## Consequences

Good: the security control point is now independent and honest; the run gate and recon share one
scan-execution classifier; severity is available for the reviewer, the report, and future tiering.
Bad / watch: stricter parking on no-Docker or flaky-scanner runs (the deny-by-default cost).

Follow-ups (each its own MR):
- **Coverage-based scan-completeness oracle (the red-team-round-2 successor).** Trust a scanner's
  `clean` only when its scanned-file set (`paths.scanned`) covers the repo's scannable files, rather
  than blocklisting semgrep skip reasons or reading gitleaks' (absent) completeness channel. Closes the
  silently-skipped-file false-CLEAN class the STOP rule escalated. Highest-priority security follow-up.
- **SCA/deps scanner (Trivy)** — CODEOWNERS-gated (`infra/`, `allowlist.py`).
- **Charter-posture enforcement seam** — make `free/business/regulated` scale the veto + enable
  severity tiering (the first ADR-0046 enforcement consumer).
- **Threat-model-note artifact** on risky diffs (deterministic diff-risk trigger).
- **Recon per-finding severity fidelity** (`_observe` currently hard-codes critical).

## Red-team scope card (post-merge)

- **Target:** this MR (the security-gate change), not "the codebase".
- **Successor?** No planned feature kills this class → durable, load-bearing → **~3 rounds**.
- **Probes:** (a) false-green re-open — a crafted scanner stdout that parses to `[]` at a bad exit;
  (b) exit-0-with-empty-stdout trusted as clean; (c) `scan_enabled`/`--no-scan` opt-out abused to
  skip the deny on a run that should verify; (d) a partial-unavailable (one scanner crashes) that
  must still park; (e) monotonicity / decision-table regression (any existing ship turned into a
  different outcome by the `clean` default). **Disposition every finding** per CLAUDE.md; **STOP** if
  two rounds surface the same class.

## Red-team — round 1 done (2026-07-23, pre-merge, 4 refute-agents)

Ran before merge (strictly safer — catch before landing). 4 adversarial agents: scan-layer, opt-out
abuse, gate-layer, recon-lift+resume. **1 FIX-NOW fixed + re-verified; STOP rule not tripped.**

- **FIX-NOW (fixed):** the semgrep **partial/errored scan false-green**. `emitted_report` checked JSON
  well-formedness, not report *completeness* — a semgrep run that exits 0 with `results:[]` but a
  non-empty `errors` array (a file it could not parse) read as `clean` and shipped with that file
  unscanned. Fixed with a per-scanner `Scanner.reported_completely` (semgrep requires an empty
  `errors`; gitleaks requires its top-level array shape); `run_one` now trusts a zero-finding verdict
  only on a complete report, and a partial scan → `unavailable` (findings still ride along). Regression
  tests added (`test_run_scan_semgrep_partial_errors_is_unavailable_not_clean` + siblings). Also
  hardened the semgrep parser against a non-dict `extra` (fails closed).
- **ACCEPT (documented, fail-safe):**
  1. **Skip-scan bypass routes.** `plan→gate` (early park) and `capture/test→supervise→gate` (give-up)
     reach the gate without `scan_node`, so `security_status` is absent → defaults `clean`. But those
     routes ALWAYS carry a validation blocker (`validation_unavailable`/`validation_failed`) → they
     park in every mode and can never reach an all-clear gate. Deny-by-default security is enforced on
     the **delivery** path (which always runs `scan→review→…→gate`); the bypass routes rely on the
     validation gate. Confirmed independently by 3 of 4 agents. A future change that let those routes
     deliver would need to re-add the security check.
  2. **Old-checkpoint migration boundary.** A run parked before this change and rehydrated post-upgrade
     reads `security_status` absent → `clean` — but it parked on origin/main for reasons that persist,
     and `security_unverified` didn't exist there, so it is no worse than pre-change (monotonic for old
     payloads; documented in `state.py`/`gate.py`).
  3. **Producer↔gate status coupling.** The gate matches the literal `"unavailable"`; the producer
     `SecurityStatus` vocabulary lives across the package boundary in `tools/scan.py`. Currently aligned
     (fails safe), and now **pinned by a contract test** (`test_producer_to_gate_status_contract`) so a
     new can't-verify status can't silently round to clean.
- **Verified sound (no break):** the reviewer-silence backstop cannot be satisfied with `unavailable`
  present; the serialized/resume path parks (the deny rides in `reasons`, which is what
  `autonomous_resolution` reads); `security_status` is a **persisted state read**, not a `ctx`
  recompute, so a security-parked run re-parks on restart (defeats the ADR-0057 resume false-ship
  class — reproduced); the recon-classifier lift is byte-identical (`recon._run_one is
  tools.scan.run_one`); `req.scan` defaults `True` so the gate fires on every default API/autonomous
  path; monotonicity holds (24-row table byte-identical).

## Red-team — round 2 done (2026-07-23, re-attack the round-1 fix) — STOP-RULE TRIPPED

One agent re-attacked the new `reported_completely` completeness code.

- **Finding (confirmed false-ship, HIGH):** the `errors[]` check catches parse errors but not a
  **silently-skipped file**. semgrep's default `--max-target-bytes 1000000` skips files >1MB, and
  `too_many_matches` truncation skips a file — both leave `results:[]` **and `errors:[]`** (and under
  `--quiet` the skip isn't even in `paths.skipped`), so a vuln planted in a >1MB file read as `clean`
  and would ship. Traced to semgrep's documented behavior (size skip "is not an error condition").
- **STOP RULE TRIPPED:** this is the **same defect class** as round 1 — "semgrep completeness detected
  by enumerating individual JSON signals, and there is always another signal." Per CLAUDE.md we do NOT
  land a third signal-enumeration patch. Disposition = **deterministic stopgap + ESCALATE-TO-SUCCESSOR**:
  - **Stopgap applied (not enumeration):** `SemgrepScanner.command()` now passes `--max-target-bytes 0`,
    removing the silent size skip at the source (the single most-reachable vector). Fails safe — a file
    too large to scan in the sandbox's caps times out → `unavailable` → park. Plus a fail-closed guard
    on a malformed (non-list) `errors` channel.
  - **ESCALATE:** the general scan-completeness problem (too_many_matches, and gitleaks having no
    completeness channel at all — probe 2, ACCEPT residual) goes to a **coverage-based
    scan-completeness oracle** successor: trust `clean` only when `paths.scanned` covers the repo's
    scannable file set, rather than blocklisting skip reasons. Logged on `docs/roadmap.md` under the
    security arc. Do NOT third-round this class.
- **Bounded exposure / why this is still safe to ship:** the residual is **strictly narrower than
  origin/main**, which false-greened on ANY missing/crashed scanner; ADR-0076 closes the broad case and
  the size vector, leaving only a *deliberately-crafted skip* (an unusual >1MB source file, or a
  too_many_matches file) reading clean. gitleaks still scans for **secrets** independently (no size
  skip), so the exploitable slice is a SAST-class vuln in a big file — narrow, in the operator's own
  target repo, and killed by the coverage successor. Fails toward a false-CLEAN only on that crafted
  skip; every other path fails toward a park.
- **Everything else re-verified sound:** no bypass via falsy `errors` (unreachable — semgrep's output
  structure isn't repo-controllable), a hostile-file-forces-park is a nuisance not a ship, no recon
  regression (35 pass / 1 docker-skip).

**Red-team verdict:** round 1 → 1 FIX-NOW fixed; round 2 → same-class recurrence, STOP-rule honored,
deterministic stopgap applied + escalated to the coverage-oracle successor. `red-team: done (2 rounds,
STOP-rule tripped → successor logged)`.
