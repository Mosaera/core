"""The governance benchmark — grades the SYSTEM, not the engine.

MCB asks one question: can the coder produce correct code from a **good** brief. Everything
upstream of that — does the system notice an ambiguous requirement, does it ask the operator
instead of guessing, does an answer given once stop being asked — is invisible to it. That
blindness is not theoretical: a standing decision sat inert in the product for its entire life and
nothing noticed, because the only instrument we trusted could not reach the layer it lived in.

This suite is deliberately SEPARATE from MCB rather than an extension of it. MCB stays frozen and
comparable — it is the capability floor, and a floor you keep editing is not a floor.

**Two things it must get right, or it measures the wrong thing.**

*Asking is sometimes the failure.* If the answer is discoverable in the code, asking the operator
is friction, not governance. A suite that only rewards asking would score blindness as a virtue —
the same trap as MCB's Autonomy dimension, which scores "parked for a human" at 30/100. Hence the
control case, and hence `asked` being scored as precision AND recall rather than a count.

*Machinery is not judgement.* The deterministic arm stubs the model, so it measures whether a
detected ambiguity ROUTES to the operator — not whether the PM would have detected it. Only the
opt-in arm, which runs a real coder over a seed, involves the model that writes the acceptance.
Conflating those two would be exactly the over-claim this suite exists to prevent.

Cases are `G-NN` — unmistakably distinct from `MCB-NN`, because a reader who confuses the two will
also confuse what each number means.
"""

from __future__ import annotations

from mosaera_core.govbench.cases import GovCase, available_gov_cases, load_gov_case
from mosaera_core.govbench.store import GovStore

__all__ = ["GovCase", "GovStore", "available_gov_cases", "load_gov_case"]
