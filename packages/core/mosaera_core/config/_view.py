"""The settings-page VIEW of the knob spec: each knob's effective value plus its provenance.

Separated from ``_knobs.py`` (which owns the spec and the layering) because this is the read model
one caller needs — the settings API — and folding it back in pushed that module over the 500-line
ceiling. The split is along a real seam: ``_knobs`` answers *what is this knob worth*, this module
answers *why, and what would override it*.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mosaera_core.config._knobs import (
    GENERAL_KNOBS,
    _coerce_knob,
    selected_profiles,
)
from mosaera_core.config._profiles import EFFECTS, derived_by, resolve_profiles
from mosaera_core.config._visibility import visibility_of


def general_settings_view(env: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Per-knob effective value + provenance for the settings UI: ``{field: {value,
    source, kind, env, choices, clamped_by}}`` where source is ``env`` (pinned by an env var →
    read-only in the UI) | ``stored`` (set in the UI) | ``default``.

    ``clamped_by`` names a knob whose value OVERRIDES this one on some runs — today only
    ``autonomous_verified``, which forces the ``POSTURE_FORCED_KNOBS`` on for every autonomous run
    (ADR-0046 §2: posture clamps knobs and may only restrict). It is deliberately NOT folded into
    ``source``: env-pinning is global and static, whereas this clamp is CONDITIONAL — the stored
    value still governs guided and ad-hoc runs — so the UI must show it without disabling the
    field. Four of these are rendered as independent toggles, and before this the operator had no
    way to learn that switching them off did nothing in the mode the product defaults to."""
    from mosaera_core.config._posture import POSTURE_FORCED_KNOBS

    e = os.environ if env is None else env
    from mosaera_core.settings_store import read_settings

    stored = read_settings(Path(e.get("MOSAERA_HOME", ".mosaera")))
    out: dict[str, dict[str, Any]] = {}
    verified = _effective_knob("autonomous_verified", e, stored)
    profiles = selected_profiles(e, stored)
    derived, provenance = resolve_profiles(profiles), derived_by(profiles)
    for k in GENERAL_KNOBS:
        env_v = _coerce_knob(k.kind, e.get(k.env))
        stored_v = None if env_v is not None else _coerce_knob(k.kind, stored.get(k.field))
        if env_v is not None:
            source, value = "env", env_v
        elif stored_v is not None:
            source, value = "stored", stored_v
        elif k.field in derived:
            source, value = "profile", derived[k.field]
        else:
            source, value = "default", k.default
        out[k.field] = {
            "value": value,
            "source": source,
            "kind": k.kind,
            "env": k.env,
            "choices": list(k.choices) if k.choices else None,
            # What this knob DOES, in a sentence. A profile summary that lists knob
            # IDENTIFIERS predicts nothing for the reader, which is what made the profiles
            # read as theatre; the effect line is the fix (ADR-0122 §5).
            "effect": EFFECTS.get(k.field),
            # Presentation only: the UI renders `core`, tucks `developer` behind a
            # disclosure and drops `internal`. Hidden is NOT locked — every knob here stays
            # settable by its env var whatever this says (ADR-0122 §6).
            "visibility": visibility_of(k.field),
            # The profile this knob WOULD take its value from, reported even when env or a stored
            # value outranks it — that is exactly when an operator needs to see that their profile
            # is being overridden here. `source` says which layer won; this says which profile is
            # in play. Independent of `clamped_by`, which is a run-time override, not a layer.
            "derived_from": provenance.get(k.field),
            "clamped_by": (
                "autonomous_verified" if verified and k.field in POSTURE_FORCED_KNOBS else None
            ),
        }
    return out


def _effective_knob(field: str, e: Mapping[str, str], stored: Mapping[str, Any]) -> Any:
    """The env > stored > default value of one knob — the same layering the view reports."""
    k = next((x for x in GENERAL_KNOBS if x.field == field), None)
    if k is None:
        return None
    env_v = _coerce_knob(k.kind, e.get(k.env))
    if env_v is not None:
        return env_v
    stored_v = _coerce_knob(k.kind, stored.get(k.field))
    return stored_v if stored_v is not None else k.default
