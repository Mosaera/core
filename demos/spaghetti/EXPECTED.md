# Expected outcome — script-kiddie spaghetti (weak oracle)

**Shape:** `.py` files, **no tests, no pytest config**, tangled + duplicated code.
`PythonPack.detect` finds no suite → `_scripts_plan` → `python -m compileall`,
validation **strength = `shallow`** (syntax-only, not behavioural).

**What it demonstrates:** the weak-oracle testless path.
- `oracle_unverified` **never fires** (it only fires on `strength == "suite"`), so
  the oracle bar is just "it compiles."
- The reviewer-silence backstop requires `strength == "suite"`, so a **silent
  reviewer parks** — a shallow run can only deliver on an **explicit reviewer
  APPROVE**.

**Terminal outcome:**

| Situation | Terminal bucket |
|---|---|
| Reviewer explicitly APPROVEs the median change (compiles, looks right) | `clean_deliver` (but only syntax-validated — honestly weak) |
| Reviewer silent / requests changes | `honest_park` (nothing behaviourally validated this) |

**Bucket to expect:** `honest_park` on a silent reviewer, or a syntax-only
`clean_deliver` on an explicit approve — never a *behaviourally*-verified ship,
which is the honest truth for a repo with no tests. This is the case the
test-stewardship functions (Proctor-owned per ADR-0058 — not a new role) would
improve: author real tests for a testless repo so the oracle has something to
stand on.
