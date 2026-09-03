# Expected outcome — greenfield (build from scratch)

**Shape:** an **empty** git repo (no commit). Cloning triggers `_init_empty`
(`clone.py`), so Mosaera scaffolds the whole project from the brief. `materialize`
creates this shape with `git init` and **no** commit.

**What it demonstrates:** the coder + oracle building from nothing. With the
autonomous posture, the Proctor authors acceptance tests from the brief; the coder
scaffolds the module + CLI + tests to pass them.

**Terminal outcome:**

| Situation | Terminal bucket |
|---|---|
| Coder builds it, an independent oracle vouches (Proctor red→green, or its own suite genuinely covers) | `clean_deliver` |
| Coder builds it but only its own tests vouch (no independent oracle) | `honest_park` (`oracle_unverified`) |
| Coder can't converge on the Proctor's tests | `thrash_park` (the failure mode the re-baseline showed is common on local models) |

**Bucket to expect:** ideally `clean_deliver`; realistically `honest_park` or —
per the 50%-thrash re-baseline — possibly `thrash_park`. Capture whichever
happens as a live datapoint for the wrong-test work (ADR-0073/0058/0075).
