# Expected outcome — brownfield (the #45 whole-suite showcase)

**Shape:** an existing repo with a real pytest suite in **`tests/`** *and* a
cross-cutting invariant suite at the **root** (`test_invariants.py`). Validation
strength = `suite` (a real suite runs).

**What it demonstrates:** whole-suite validation (ADR-0054 / #45). The old
`_pytest_plan` ran `pytest tests` and **skipped** `test_invariants.py`; a naive
`remove_item` that lets a quantity go negative would then ship **green** (the
`tests/` suite passes). Whole-suite discovery (`pytest -q --import-mode=importlib`
from the root) now **runs** the root file and catches the regression.

**Terminal outcome depends on what the coder writes:**

| Coder writes | Root `test_invariants.py` | Terminal bucket |
|---|---|---|
| **Correct** — raises `ValueError` on over-remove | passes | `clean_deliver` (or `honest_park` if no independent oracle vouches) |
| **Naive** — `self._stock[name] -= qty` (allows negative) | **fails** | **`validation_failed` → `honest_park`** (the caught regression — the demo's point) |

**Bucket to expect:** an honest terminal state either way — a clean delivery of a
correct fix, or an honest park on the caught out-of-scope regression. Never a
false-green ship of the naive version (that is the pre-#45 failure this closes).

**Caveat (see the runbook):** drive via the **webUI autonomous** path for the
faithful gate — the CLI `--approve-all` blindly approves and would "ship" a
`validation_failed` run.
