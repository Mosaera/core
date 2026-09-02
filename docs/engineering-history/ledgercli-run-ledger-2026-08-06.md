# LedgerCLI — the run ledger (baseline, 2026-08-05/06)

**What this is.** Every run against the LedgerCLI specimen, with its outcome and the finding it
produced. This is the **baseline** the engine is measured against from here: the first project driven
end to end to completion, and the cost of getting there.

Specimen: `LedgerCLI` (greenfield), live on `mosaera.rengifo.me`, project `proj-ledgercli-511c67`.
Models: `qwen3-coder:30b` (producer/Proctor/reviewer), `gpt-oss:20b` (PM/design). Local Ollama, $0.

## Milestones

| # | milestone | run | evidence |
|---|---|---|---|
| 1 | **First delivery** — Slice 1, guided | `20260806-201444-5dc991` | `clean_deliver`, commit `c61a68e`, 5 tests green. The 13th run on the item |
| 2 | **First autonomous delivery** — Slice 2 | `20260806-205148-53e2ea` | `clean_deliver`, commit `0cd9f49`, no operator at any gate |
| 3 | **First intake refusal** — Slice 3 | `20260806-205850-033b61` | `honest_park` / `under_specified` at **0 tokens**, before any work |
| 4 | **Project complete** — Slice 3 | `20260806-211121-6bd0af` | `clean_deliver`, commit `1294030`, all 3 slices delivered |
| 5 | **First engine-caused follow-up** — item #86 | `20260806-215759-0ba3b2` | the [[F57]] month bug, filed and re-run autonomously |

## The ledger

20 runs. **12 consecutive cancellations before the first delivery.**

| run (HHMMSS-id) | item | status | outcome | commit |
|---|---|---|---|---|
| `185615-a41c8c` | 83 | CANCELLED | — | — |
| `191856-69c82c` | 83 | CANCELLED | — | — |
| `042356-a5ecf3` | 83 | CANCELLED | — | — |
| `060746-f75d59` | 83 | CANCELLED | — | — |
| `071504-0cb0b1` | 83 | CANCELLED | — | — |
| `074310-721ec9` | 83 | CANCELLED | — | — |
| `080913-0d3928` | 83 | CANCELLED | — | — |
| `130919-fff020` | 83 | CANCELLED | — | — |
| `133625-4d7c60` | 83 | CANCELLED | — | — |
| `140201-44bb12` | 83 | CANCELLED | — | — |
| `154604-229044` | 83 | CANCELLED | — | — |
| `191349-668b6a` | 83 | CANCELLED | — | — |
| **`201444-5dc991`** | 83 | **APPROVED** | `clean_deliver` | **`c61a68e`** |
| `204007-4d44ca` | 83 | CANCELLED | `honest_park` | — |
| `204216-bbe28c` | 83 | CANCELLED | `honest_park` | — |
| **`205148-53e2ea`** | 84 | **APPROVED** | `clean_deliver` | **`0cd9f49`** |
| `205850-033b61` | 85 | INCOMPLETE | `honest_park` (`under_specified`) | — |
| `210846-ce9246` | 85 | CANCELLED | `honest_park` | — |
| **`211121-6bd0af`** | 85 | **APPROVED** | `clean_deliver` | **`1294030`** |
| `215759-0ba3b2` | 86 | RUNNING | — | — |

**Note the diagnosis column.** Every run before `191349` records `-` — not because they ended
mysteriously but because [F50](ledgercli-friction-log-2026-08-05.md) meant a cancelled run persisted
no diagnosis at all. Twelve runs of blank history is what made the PM invent causal stories about
them. The `honest_park` entries from `204007` onward are the fix working.

## Cost

| slice | posture | calls | tokens | budget events |
|---|---|---|---|---|
| Slice 1 | guided (9 gates, 4 denials) | 83 | 764k | 1 park, raised |
| Slice 2 | autonomous | 56 | 435k | 2 parks, raised |
| Slice 3 | autonomous | 61 | 665k | none (5M cap) |

Project total across all 20 runs: **~6.9M tokens, 738 calls**, $0 (local). Input:output ≈ 35:1 — the
flat context tax dominates, so cost tracks **round trips**, not output volume.

## What the ledger says

**The failure was never the coding.** Across the whole project the producer never cheated: `#64`
measured 0 corruption in 6 seeded-bad-oracle runs, and no live run tampered with a protected test.
Every delivery blocker was upstream of implementation — an unsatisfiable bar (F44), a vacuous bar
(F52), an escalation with no resolver (F49), an under-specified item (the intake refusal).

**The gates earn their place, and their cost is legible.** Slice 1 took 9 gates and 4 operator
denials, none of which any deterministic check would have caught. Slices 2 and 3 took none. The
difference was not the posture — it was whether the criteria were checkable and whether the Proctor
happened to draw a good sample.

**The Proctor is high-variance, and that is the headline.** Same model, same project, within one day:
three `assertTrue(True)` bodies; a first-draft bar that avoided the F44 date pin unprompted; an
attempt to gut its own approved bar (F53); and a suite that deliberately declined to over-specify
because "order of categories in output is not specified". Variance — not a capability ceiling — is
what to measure next.

**Completion is not correctness.** All three slices delivered and the project reads DONE, yet
[[F57]] shipped: `status` ignores months entirely, and the authored tests never mention a month.
Every control passed on its own terms. A human reading the diff is still the last line, and item #86
exists to test whether the loop closes without one.
