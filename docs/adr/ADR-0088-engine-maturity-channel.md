# ADR-0088: The maturity channel — a second axis, because a version number is not a trust claim

- Status: accepted
- Implementation: shipped
- Date accepted: 2026-08-07
- Owners: Mosaera core
- Related issue / MR: engine-versioning follow-up (`docs/roadmap.md` → Continuous — independent debt)
- Supersedes / Superseded by: — (**extends** [ADR-0055](ADR-0055-engine-versioning.md); supersedes nothing)
- Related threat model: — (no trust-surface change)
- Review trigger: an ADR-0061 v1.0 gate goes green, or `1.0.0` is cut

**Decision summary:** Publish the engine's maturity as a **separate constant** `mosaera_core.__maturity__`
∈ `alpha | beta | rc | stable`, parallel to `__version__` rather than encoded in it, and stamp it
wherever the version is already shown (`mosaera --version`, the API `/config`, the dashboard header).
The ladder is anchored to the four measured [ADR-0061](ADR-0061-v1-measured-definition-of-done.md)
gates, and advancing it requires the same benchmark evidence a version bump requires. Today's reading
is **`beta`**.

## Context

[ADR-0055](ADR-0055-engine-versioning.md) versions the engine `0.x`, maturity-anchored, with `1.0`
reserved for production-stable; its 2026-07-23 amendment rations MINOR/MAJOR toward that milestone so
completed arcs bump PATCH. Both decisions are sound and stay in force. They leave one thing unsaid.

**The number cannot carry the trust claim, and it was being read as though it did.** `0.6.0` had sat
unchanged since 2026-07-19 — correctly, because the amendment made arcs cheap in version terms — but
the stillness read as neglect rather than as policy. More importantly, *nothing anywhere in the
product stated how much the engine may be trusted*. A `0.x` prefix is a convention a reader has to
know; "not production-authorized" is a statement the product owes its operator explicitly. The two
questions are genuinely different:

- **`__version__` answers "how far along?"** — a monotonic, ordered, comparable fact. It is stamped
  into run receipts, the benchmark trend `history.jsonl`, and `runs.engine_version`, and its ordering
  is load-bearing for all three.
- **`__maturity__` answers "how much may I trust this?"** — a bounded, *non-monotonic* judgement
  against stated criteria. It can move without the number moving, and (in principle) move backward if
  a gate regresses.

Collapsing them loses information in both directions.

## Decision

**1. A separate constant, on a closed ladder.** `mosaera_core.__maturity__: Final[str]`, validated
against `MATURITY_CHANNELS = ("alpha", "beta", "rc", "stable")`.

**2. The ladder — criteria stated first, the label read off them.** This ordering is the whole
anti-gaming property: the criteria below were written before the current label was chosen, so the
label is a *finding*, not a preference.

| Channel | Criterion |
|---|---|
| `alpha` | Runs end-to-end, but outcomes are **not** measured on a held-out benchmark. |
| `beta` | Outcomes are measured on a held-out benchmark with published snapshots; the trust boundary and honest terminal outcomes are enforced. **Not production-authorized.** |
| `rc` | **3 of the 4** ADR-0061 v1.0 gates green on a single held-out run. |
| `stable` | **All four** ADR-0061 gates simultaneously green. Ships as `1.0.0`. |

**3. Today's reading is `beta`.** Earned at `0.5.0`, when the reliability scoreboard
([ADR-0053](ADR-0053-reliability-scoreboard.md)) made outcomes measurable and every release since has
carried a benchmark snapshot. It is emphatically **not `rc`**: `0.6.0` measured 65.3%
clean-conclusion against gate 1's ~99% bar, and gates 2/3/4 are open. Retroactively, `0.1.0`–`0.4.x`
were `alpha` by the ladder's own definition — there was no measurement to publish.

**4. Advancing the channel requires the same evidence a version bump requires** — a `CHANGELOG.md`
entry whose benchmark snapshot names **the suite, the run count, and the posture configuration**
(the ADR-0061 gate-2 amendment's wording: a rate is only a result when the distribution it bounds is
named). A maturity claim with no snapshot behind it is exactly the "demoed rather than measured"
failure ADR-0061 forbids. *Evidence-Gated Advancement* applies to claims about the engine, not only
to claims made by it.

**5. Stamped wherever the version already travels** — `mosaera --version` (`mosaera 0.6.0 (beta)`),
the API `/config` payload, and the dashboard header badge. No new plumbing: these are the seams
ADR-0055 already opened. The badge is **hidden at `stable`**, where the absence of a channel is
itself the signal.

**6. The number stays a plain PEP 440 release — `X.Y.Z`, never a pre-release suffix.** This is the
load-bearing technical reason maturity is a separate constant and not `0.7.0b1`. Python packaging is
[PEP 440](https://peps.python.org/pep-0440/), not SemVer: a SemVer-style `0.6.1-beta.1` is *invalid*
in a `pyproject.toml`, and `packaging` silently normalizes it to `0.6.1b1` in metadata, filenames and
lockfiles while a hand-written `__version__` keeps the hyphen. That is drift *by normalization* —
undetectable by reading either file. Enforced by `test_version_is_a_plain_release_not_a_prerelease`
and by `scripts/bump_version.py`, which rejects the shape with that explanation.

**7. Deliberately NOT stamped into the run seal.** `make_receipt_id(run_id, commit_sha,
engine_version, …)` and the `runs.engine_version` column keep the version alone. Adding a field to
the receipt preimage would change **every** receipt id — an artifact-contract break requiring an ADR,
a migration, and replay analysis under *Artifact-Centric Execution* — to record something already
derivable from the version via this CHANGELOG. Stated here so a future reader does not "fix" the
omission.

## Options considered

- **A separate `__maturity__` constant (CHOSEN).** Keeps every `pyproject.toml` a plain release, keeps
  the version's ordering semantics clean, and lets the trust claim move independently of the number —
  which is the actual requirement. Matches how release channels work in practice (Chrome, Android:
  channel and version are orthogonal).
- **PEP 440 pre-release suffix in the number — `0.7.0b1` (REJECTED).** One string instead of two, but
  it makes every arc a pre-release *of a future version we have not decided on*, which contradicts
  ADR-0055's PATCH-per-arc amendment. It also churns all 7 pyprojects on every maturity move and
  invites the invalid hyphenated spelling (§6).
- **Docs-only prose ("Mosaera is beta software") (REJECTED).** Cheapest, unenforceable, invisible to
  the CLI and UI, and it goes stale exactly the way the un-explained `0.6` label already did. A status
  a human retypes is structurally unfixable (the `check_doc_claims.py` premise).
- **Renumbering to signal maturity — e.g. resetting to `0.2.0` (REJECTED).** Considered and declined:
  `0.6.0` is already stamped into run receipts, the benchmark trend, and `runs.engine_version`, all of
  which rely on the ordering. Renumbering downward orphans that audit chain, breaks `uv`/`pip`
  resolution, and reverses ADR-0055's explicit rejection of the low register.

## Security implications

None. A display/metadata string on the same non-authenticated `/config` payload that already carries
the version — no gate, no trust boundary, no secret, no authorization effect. Specifically: the
channel **does not** relax or tighten any control, and no code branches on it. Advertising
`beta` discloses nothing an attacker cannot read from the public CHANGELOG.

## Operational implications

No migration, no new dependency, no schema change (§7 keeps it out of the seal). A maturity move is
one line in `packages/core/mosaera_core/__init__.py`, or `scripts/bump_version.py --maturity <ch>`
alongside a version bump. An older dashboard against a newer API degrades cleanly: the web client
types `maturity` as optional and renders the version alone when it is absent.

## Consequences

- **Good:** the engine states its own trustworthiness where an operator will actually see it, and
  `0.6.0` stops being read as neglect. The two questions "how far" and "how much may I trust it" can
  now move independently.
- **Good:** the `rc`/`stable` rungs make ADR-0061 operationally visible — the gates now have a
  user-facing consequence rather than living only in an ADR.
- **Cost:** two constants to keep honest instead of one. Mitigated by `scripts/bump_version.py` and
  the widened `test_cli_version.py` guards, which fail on an off-ladder value.
- **Watch:** the channel is a claim, and claims decay. The review trigger (a gate going green) is the
  intended prompt; `docs/runbooks/versioning.md` carries the operational procedure.
