"""Presets are an objective POLICY; the operator's own models fill them (#119).

**Why this is not a table of model names.** Mosaera is BYOM. Shipping "balanced means
`qwen3-coder:30b`" would push every newcomer at one vendor's model and quietly assert a ranking —
and the ranking is the part we cannot back: the whole measured corpus was produced on ONE binding,
and `docs/engineering-history/` contains no per-model comparison. A preset that claimed to select
"your strongest model" would be asserting a fact nobody measured, which is the exact
instrument-trust failure this project exists to argue against.

**So a preset routes on axes that are objectively evaluable, and only those:**

===================  =========  ===============================================================
axis                 usable     from
===================  =========  ===============================================================
on-box vs off-box    **yes**    ``provider_is_local`` / ``endpoint_is_on_box`` — a fact
price                **yes**    ``settings.model_prices``; a local model is free — a fact
context window       no         neither Ollama's ``/api/tags`` nor any list-models response
                                carries it, so we cannot route on it honestly
"strongest"          no         unmeasured; see above
===================  =========  ===============================================================

The shipped constant is therefore a POLICY (this module), while what gets PERSISTED stays the
existing ``Settings.cost_modes`` shape (role → ``RoleModel``) — no enum change, no migration. The
difference is where those values came from: a policy evaluated over the operator's real inventory
and then CONFIRMED by them, rather than a list we chose.

A role the policy cannot satisfy resolves to **nothing, with a reason**. Never to a guess: a
silently-substituted model is a run whose producer was not the one the operator picked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mosaera_core.config import Settings
    from mosaera_core.config._types import RoleModel

#: How a policy picks among the candidates it is allowed to use.
#: ``cheapest`` — lowest priced (local counts as free, so it wins wherever it qualifies).
#: ``operator`` — we do not pick at all; the operator nominates, and the wizard asks.
Prefer = Literal["cheapest", "operator"]

#: Where a policy may source a model from. ``on_box`` is the honest privacy guarantee: nothing this
#: role sends can leave the machine. ``any`` permits hosted providers too.
Locality = Literal["on_box", "any"]


@dataclass(frozen=True)
class PresetPolicy:
    """What one preset MEANS, in terms a machine can evaluate and an operator can check."""

    locality: Locality
    prefer: Prefer
    #: One sentence, shown verbatim in the wizard and the docs. It must describe the POLICY, never
    #: a capability claim — "cheapest that runs here", not "good enough for real work".
    summary: str


#: One entry per shipped ``COST_MODES`` id. The ids and their UI labels already exist
#: (``presetLabel`` renders them "Local · Free" / "Balanced" / "Quality · Cloud"), so this adds
#: meaning to a control the product already has rather than inventing another one.
#:
#: **No model name appears here, deliberately** — `test_presets` pins that.
PRESET_POLICY: dict[str, PresetPolicy] = {
    "economy": PresetPolicy(
        locality="on_box",
        prefer="cheapest",
        summary="Only models running on this machine. Nothing you send can leave the box.",
    ),
    "balanced": PresetPolicy(
        locality="any",
        prefer="cheapest",
        summary="Prefers models on this machine; falls back to the cheapest you have configured.",
    ),
    "premium": PresetPolicy(
        locality="any",
        prefer="operator",
        summary="You nominate the model for each role. We rank nothing for you.",
    ),
}


@dataclass(frozen=True)
class Candidate:
    """One model the operator actually has, with the facts a policy may route on."""

    provider: str
    model: str
    on_box: bool
    #: Input $/Mtok if the operator priced it; ``None`` = unpriced, which is NOT free.
    price: float | None

    @property
    def free(self) -> bool:
        return self.on_box


@dataclass(frozen=True)
class Resolution:
    """What a role got, and WHY — the reason is shown next to the row in the wizard.

    ``binding`` is ``None`` when the policy could not be satisfied. That is a first-class outcome:
    the operator is told which role is unserved and why, instead of being handed a substitute they
    did not choose.
    """

    role: str
    binding: RoleModel | None
    reason: str


def inventory_from(settings: Settings, ollama_tags: tuple[str, ...]) -> list[Candidate]:
    """The operator's real inventory — what is ACTUALLY available, never what is merely configured.

    **The distinction this function exists to hold, learned live on 2026-08-25.** It used to union
    every configured role binding into the candidate list. On a fresh machine that means the stock
    defaults (`gpt-oss:20b`, `qwen3-coder:30b`) became candidates marked `on_box=True` — so with
    Ollama unreachable and nothing pulled, the setup screen told a newcomer *"all 5 roles →
    gpt-oss:20b — runs on this machine, so nothing leaves the box"*. Every word of that was false,
    and it is the precise failure this whole issue exists to end: a configured default presented as
    an available fact.

    So availability has to be OBSERVED, per provider:

    - **Ollama** — the tags are the authoritative list of what is pulled, and we have them. A
      binding not in the tags is not available, whatever the config says. Nothing is added here
      beyond ``ollama_tags``; an unreachable Ollama yields no local candidates at all, which is the
      honest answer for a machine with no model server.
    - **Hosted** — availability needs a key. A provider with none cannot serve the binding, and
      including it would let a policy resolve to something that cannot run (the same defect wearing
      a different provider).
    """
    from mosaera_core.models import endpoint_is_on_box
    from mosaera_core.preflight import _provider_key

    out: list[Candidate] = [
        Candidate(provider="ollama", model=tag, on_box=True, price=None) for tag in ollama_tags
    ]
    seen = {(c.provider, c.model) for c in out}
    for role in ("pm", "coder", "reviewer", "tester", "critic"):
        binding = settings.role_model(role)  # type: ignore[arg-type]
        if not binding.model or (binding.provider, binding.model) in seen:
            continue
        if binding.provider == "ollama":
            continue  # not in the tags ⇒ not pulled ⇒ not available. See the docstring.
        if not _provider_key(settings, binding.provider):
            continue  # no key ⇒ cannot serve it, so it is not a candidate
        # `endpoint_is_on_box` answers this for BOTH cases — an inherently-local provider and an
        # operator-declared loopback endpoint — and it is deny-by-default about the second.
        on_box = endpoint_is_on_box(settings, binding.provider)
        rate = settings.model_prices.get(binding.model)
        out.append(
            Candidate(
                provider=binding.provider,
                model=binding.model,
                on_box=on_box,
                price=float(rate[0]) if rate else None,
            )
        )
        seen.add((binding.provider, binding.model))
    return out


def resolve_preset(
    policy: PresetPolicy,
    inventory: list[Candidate],
    *,
    roles: tuple[str, ...] = ("pm", "coder", "reviewer", "tester", "critic"),
) -> list[Resolution]:
    """Apply ``policy`` to ``inventory``. Pure, deterministic, and it never invents a binding.

    Every role gets the same answer, because the axes this routes on say nothing about roles —
    pretending otherwise would smuggle back the capability ranking we just refused to assert. The
    per-role table exists so the OPERATOR can differentiate, which is a judgement they can make and
    we cannot.
    """
    from mosaera_core.config._types import RoleModel

    if policy.prefer == "operator":
        return [
            Resolution(role, None, "you choose — this preset ranks nothing for you")
            for role in roles
        ]

    allowed = [c for c in inventory if policy.locality == "any" or c.on_box]
    if not allowed:
        why = (
            "no model is available on this machine"
            if policy.locality == "on_box"
            else "no model is configured at all"
        )
        return [Resolution(role, None, why) for role in roles]

    pick = _cheapest(allowed)
    reason = (
        "runs on this machine, so nothing leaves the box"
        if pick.on_box
        else f"cheapest configured model (${pick.price}/Mtok in)"
        if pick.price is not None
        else "the only configured model"
    )
    binding = RoleModel(provider=pick.provider, model=pick.model)
    return [Resolution(role, binding, reason) for role in roles]


def _cheapest(candidates: list[Candidate]) -> Candidate:
    """Lowest cost first; on-box counts as free.

    An UNPRICED hosted model sorts last, not first. Absent price data is not evidence of a low
    price, and treating it as zero would let the cheapest-policy silently pick the model whose cost
    we know least about — a cost gate that fails open (compare `cloud_tier_allowed`, which requires
    a price entry for exactly this reason).
    """

    def key(c: Candidate) -> tuple[int, float, str]:
        if c.on_box:
            return (0, 0.0, c.model)
        if c.price is None:
            return (2, 0.0, c.model)
        return (1, c.price, c.model)

    return sorted(candidates, key=key)[0]


def as_cost_mode(resolutions: list[Resolution]) -> dict[str, RoleModel]:
    """The resolved bindings in ``Settings.cost_modes``' existing shape.

    Unresolved roles are OMITTED rather than defaulted: an omitted role falls back to the base BYOM
    binding, which is the documented behaviour of that structure, and writing a guess would hide
    the very gap the wizard just showed the operator.
    """
    return {r.role: r.binding for r in resolutions if r.binding is not None}
