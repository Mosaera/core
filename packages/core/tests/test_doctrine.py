"""Global planning doctrine loader — deterministic, cached, trusted framing."""

from __future__ import annotations

from mosaera_core.doctrine import load_global_doctrine


def test_global_doctrine_has_trusted_framing_and_core_rules() -> None:
    d = load_global_doctrine()
    assert "## Doctrine" in d
    # Framed as trusted guidance the PM FOLLOWS — the inverse of untrusted repo data.
    assert "trusted guidance, not repository" in d
    assert "Read before you plan" in d  # a core rule survived into the injected block


def test_global_doctrine_respects_budget() -> None:
    small = load_global_doctrine(120)
    assert "truncated" in small
    # header (fixed) + capped body (≤120) + the short note — comfortably bounded
    assert len(small) <= 500
