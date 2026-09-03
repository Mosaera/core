"""Path-safety guards for URL ids that become filesystem path segments (ADR-0038)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from hypothesis import given
from hypothesis import strategies as st
from mosaera_api._pathsafe import contained_path, is_safe_id, safe_segment

# A fixed base for the property tests. It need not exist — Path.resolve() normalises either way.
_PROP_BASE = Path("/mosaera-prop-base/workspaces")


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty
        "..",  # the live parent-escape vector
        ".",  # current dir
        "../etc",  # traversal + separator
        "a/b",  # forward slash
        "a\\b",  # backslash (Windows separator)
        ".hidden",  # leading dot
        "a..b",  # embedded dot-run
        "foo/../bar",  # normalises out of base
        "%2e%2e",  # the raw encoded form, if starlette ever leaves it undecoded
        "run id",  # space
    ],
)
def test_is_safe_id_rejects_traversal_and_separators(bad: str) -> None:
    assert is_safe_id(bad) is False


@pytest.mark.parametrize(
    "good",
    [
        "20260715-143022-a1b2c3",  # run id: YYYYMMDD-HHMMSS-<6hex>
        "proj-my-app-abc123",  # project id: proj-<slug>-<6hex>
        "att-0123456789ab",  # attachment id
        "runX",
    ],
)
def test_is_safe_id_accepts_every_server_minted_shape(good: str) -> None:
    assert is_safe_id(good) is True


def test_safe_segment_raises_400_naming_the_kind() -> None:
    with pytest.raises(HTTPException) as exc:
        safe_segment("..", kind="run id")
    assert exc.value.status_code == 400
    assert "run id" in str(exc.value.detail)


def test_contained_path_blocks_parent_escape(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    with pytest.raises(HTTPException) as exc:
        contained_path(base, "..", kind="run id")
    assert exc.value.status_code == 400
    # The base's parent (which would be `.mosaera/` in production) must be untouched-able.
    assert base.parent.exists()


def test_contained_path_returns_a_real_child(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    child = base / "20260715-000000-abc123"
    child.mkdir(parents=True)
    assert contained_path(base, "20260715-000000-abc123", kind="run id") == child.resolve()


# --- property tests: prove the chokepoint is TOTAL over arbitrary input (ADR-0041) ---


@given(seg=st.text())
def test_contained_path_never_escapes_base(seg: str) -> None:
    # TOTALITY: for ANY input string — unicode, dot-runs, separators, null bytes, the lot —
    # contained_path either rejects it (400) or returns a path provably UNDER base. It must
    # never return an escaping path and never raise anything other than HTTPException. This is
    # the fuzz proof behind the ADR-0038 traversal fix.
    root = _PROP_BASE.resolve()
    try:
        result = contained_path(_PROP_BASE, seg)
    except HTTPException as exc:
        assert exc.status_code == 400
        return
    assert result == root or result.is_relative_to(root)


@given(seg=st.text())
def test_safe_segment_agrees_with_its_predicate(seg: str) -> None:
    # The boundary guard and its predicate never disagree: safe_segment returns iff is_safe_id.
    if is_safe_id(seg):
        assert safe_segment(seg) == seg
    else:
        with pytest.raises(HTTPException):
            safe_segment(seg)
