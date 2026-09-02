"""Intent profiles derive the mechanics without disturbing what an operator actually set (ADR-0122).

The load-bearing test here is ``test_no_profile_selected_changes_nothing``: profiles ship into
existing installs, and the whole safety argument for adding them outside a trust-boundary review is
that an install which never opts in resolves byte-for-byte to today's values.
"""

from __future__ import annotations

import pytest
from mosaera_core.config import (
    GENERAL_KNOBS,
    NEVER_DERIVED,
    PROFILE_DERIVED,
    coerce_general_patch,
    layer_knobs,
    resolve_profiles,
)
from mosaera_core.config._visibility import CORE, INTERNAL, visibility_of

_KNOBS_BY_FIELD = {k.field: k for k in GENERAL_KNOBS}
_PROFILE_FIELDS = tuple(PROFILE_DERIVED)


def test_no_profile_selected_changes_nothing() -> None:
    """An install that never opts in gets exactly ``Knob.default`` for every knob.

    This is the upgrade-safety property: adding the profile layer cannot re-tune a deployment
    that has not asked for it.
    """
    resolved = layer_knobs({}, {})
    for knob in GENERAL_KNOBS:
        assert resolved[knob.field] == knob.default, knob.field


def test_profile_supplies_a_value_the_operator_never_set() -> None:
    """With a profile chosen, its derived knobs take the profile's value, not the default."""
    resolved = layer_knobs({}, {"recovery_profile": "persistent"})
    assert resolved["max_reason_attempts"] == 3
    assert _KNOBS_BY_FIELD["max_reason_attempts"].default == 1
    # A knob no profile owns is untouched.
    assert resolved["sandbox_timeout"] == _KNOBS_BY_FIELD["sandbox_timeout"].default


def test_stored_value_outranks_the_profile() -> None:
    """An explicit setting wins: the profile may only fill what the operator left alone."""
    resolved = layer_knobs({}, {"recovery_profile": "persistent", "max_reason_attempts": 0})
    assert resolved["max_reason_attempts"] == 0


def test_env_outranks_the_profile() -> None:
    resolved = layer_knobs(
        {"MOSAERA_MAX_REASON_ATTEMPTS": "7"},
        {"recovery_profile": "persistent"},
    )
    assert resolved["max_reason_attempts"] == 7


def test_env_selects_the_profile_itself() -> None:
    """The profile knob is layered like any other: env > stored > default."""
    resolved = layer_knobs(
        {"MOSAERA_RECOVERY_PROFILE": "minimal"},
        {"recovery_profile": "persistent"},
    )
    assert resolved["max_reason_attempts"] == 0


@pytest.mark.parametrize("field", _PROFILE_FIELDS)
def test_every_profile_choice_derives_only_real_knobs(field: str) -> None:
    """A table entry naming a knob that does not exist would silently derive nothing."""
    for choice, derived in PROFILE_DERIVED[field].items():
        unknown = set(derived) - set(_KNOBS_BY_FIELD)
        assert not unknown, f"{field}={choice} derives unknown knobs {sorted(unknown)}"


@pytest.mark.parametrize("field", _PROFILE_FIELDS)
def test_derived_values_match_their_knob_type(field: str) -> None:
    """A bool table entry against an int knob would coerce oddly downstream."""
    for choice, derived in PROFILE_DERIVED[field].items():
        for knob_field, value in derived.items():
            kind = _KNOBS_BY_FIELD[knob_field].kind
            expected = bool if kind == "bool" else (int, float) if "int" in kind else str
            assert isinstance(value, expected), f"{field}={choice}: {knob_field}={value!r} ({kind})"


def test_profiles_never_derive_safety_knobs() -> None:
    """No profile may decide what the delivery gate permits (settings-v2 §56).

    'Aggressive' means more attempts, never weaker evidence. If a future edit adds
    ``deliver_unverified`` to a profile table, this fails rather than shipping.
    """
    for field, table in PROFILE_DERIVED.items():
        for choice, derived in table.items():
            overlap = set(derived) & NEVER_DERIVED
            assert not overlap, f"{field}={choice} derives safety knobs {sorted(overlap)}"


def test_profile_tables_are_disjoint() -> None:
    """Two profiles owning one knob would make the resolved value order-dependent."""
    seen: dict[str, str] = {}
    for field, table in PROFILE_DERIVED.items():
        for derived in table.values():
            for knob_field in derived:
                assert seen.setdefault(knob_field, field) == field, (
                    f"{knob_field} is claimed by both {seen[knob_field]} and {field}"
                )


def test_unset_or_unknown_choice_derives_nothing() -> None:
    """The read path stays total — the WRITE path is what rejects a bad value loudly."""
    assert resolve_profiles({}) == {}
    assert resolve_profiles({"recovery_profile": None}) == {}
    assert resolve_profiles({"recovery_profile": "nonsense"}) == {}


@pytest.mark.parametrize("field", _PROFILE_FIELDS)
def test_out_of_set_profile_is_rejected_on_write(field: str) -> None:
    """ADR-0005: an enumerable value is a dropdown, and the write path enforces the set."""
    with pytest.raises(ValueError):
        coerce_general_patch({field: "yolo"})


@pytest.mark.parametrize("field", _PROFILE_FIELDS)
def test_every_profile_knob_is_a_dropdown(field: str) -> None:
    knob = _KNOBS_BY_FIELD[field]
    assert knob.choices, f"{field} must declare choices"
    assert knob.default is None, f"{field} must ship UNSET so upgrades change nothing"
    assert visibility_of(field) == "core", f"{field} must be on the Core surface"
    for choice in knob.choices:
        assert choice in PROFILE_DERIVED[field], f"{field}={choice} has no derivation table"
    assert set(PROFILE_DERIVED[field]) == set(knob.choices)


def test_every_classified_knob_exists() -> None:
    """A set entry naming a knob that was renamed or removed silently classifies nothing."""
    fields = set(_KNOBS_BY_FIELD)
    assert not (CORE - fields), f"CORE names unknown knobs: {sorted(CORE - fields)}"
    assert not (INTERNAL - fields), f"INTERNAL names unknown knobs: {sorted(INTERNAL - fields)}"
    assert not (CORE & INTERNAL), "a knob cannot be both Core and internal"


def test_the_core_surface_stays_small() -> None:
    """The point of the classification is a surface a new user can read without documentation.
    Not a style rule: a Core set that drifts upward is the condition ADR-0122 §6 exists to end,
    and it drifts one defensible knob at a time."""
    core = [k.field for k in GENERAL_KNOBS if visibility_of(k.field) == "core"]
    assert len(core) <= 14, f"Core has grown to {len(core)}: {sorted(core)}"


def test_no_profile_owned_knob_is_core() -> None:
    """A knob a profile derives must not ALSO be a Core control — that would present the same
    decision twice, once as intent and once as mechanism."""
    core_derived = {f for f in _derived_fields() if visibility_of(f) == "core"}
    assert not core_derived, f"derived knobs also on the Core surface: {sorted(core_derived)}"


def _derived_fields() -> set[str]:
    out: set[str] = set()
    for table in PROFILE_DERIVED.values():
        for choice in table.values():
            out |= set(choice)
    return out
