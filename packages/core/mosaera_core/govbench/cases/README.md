# Governance cases (`G-NN`)

MCB grades the coder on a good brief. These grade the system that **produces** the brief — the half
of the product no instrument watched, which is how a standing decision sat inert for its entire
life with every unit test green ([ADR-0083](../../../../../docs/adr/ADR-0083-governance-benchmark.md)).

Cases are **fixtures**, excluded from the repo's ruff/mypy/pytest (root `pyproject.toml`) exactly
as MCB's are: a seed stands in for a user's repo, and its deliberate defects — a suite that asserts
only the old contract — are the point.

## Layout

```
G-NN/
  brief.md      # the item's ACCEPTANCE text — what the intake detectors actually read
  case.toml     # class + the PRE-REGISTERED expectations
  answer.md     # the OPERATOR's reply (MCB has no equivalent — this is the new axis)
  seed/         # optional starting repo
  grader/       # hidden acceptance suite — expensive arm only
  reference/    # known-good overlay — proves the grader is sound; never used in a real run
```

`brief.md` holds acceptance text rather than a full task description because that is the string
production inspects. Writing it as a whole brief would invite grading a different string.

## The case IS the pre-registration

`case.toml` declares what the system *should* do **before the case is ever run**: the verdict the
detectors must produce and whether an ask is the right response. Scoring then checks reality
against the declaration, so a case whose verdict disagrees with its class is a **broken case, not a
finding** — `score_governance` raises rather than reporting a low score. Two of the original five
were broken on the first run and were fixed as fixtures, not reported as results.

Unlike MCB's loader, an **unknown `case.toml` key raises**. A typo'd expectation that silently does
nothing is the worst possible bug in a suite whose entire subject is expectations.

## The classes

| class | correct behaviour | what it catches |
| --- | --- | --- |
| `undecidable` | **ask** | a named output scale with no composition rule |
| `discoverable` | **don't ask — go and look** | the answer is in the repo; asking is friction |
| `control` | **say nothing** | over-asking. Without this, `Asked` cannot fail in that direction |
| `clause-settleable` | ask **once**, never again | whether a ratified decision compounds |
| `no-op-ship` | do the work, or park | a delivery certified by a suite that cannot fail it |

`discoverable` and `no-op-ship` have **decidable** acceptance on purpose — their failure modes are
downstream of intake, so the cheap arm can only confirm they stayed silent. A green cheap arm does
not cover them.

## Adding a case

1. Write `brief.md` and declare the expectations in `case.toml`.
2. Run `pytest packages/core/tests/test_govbench.py`. If the verdicts disagree with your
   declaration, **one of the two is wrong and you must decide which before looking at any score.**
3. Shipping a grader too? Add `reference/` as well — `test_govbench_cases.py` enforces that the
   grader FAILS on the bare seed and PASSES on the reference, so an unwinnable or trivially
   satisfied case cannot merge.
