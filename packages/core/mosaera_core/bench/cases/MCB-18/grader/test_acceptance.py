"""Hidden acceptance suite for MCB-18 (atomic, aggregated op validation).

Ground truth — never shown to the agent, injected at grade time. Imports the
delivered module from the workspace cwd and asserts the applier is atomic (nothing
applied on failure, input never mutated) and that ``OperationError`` aggregates one
indexed entry per bad op.
"""

from __future__ import annotations

import pytest
from ops import OperationError, apply_operations


def test_valid_ops_apply_and_do_not_mutate_input() -> None:
    data = {"a": 1, "b": 2, "gone": 9}
    operations = [
        {"action": "set", "key": "c", "value": 3},
        {"action": "delete", "key": "gone"},
        {"action": "increment", "key": "a", "amount": 10},
    ]
    result = apply_operations(data, operations)
    assert result == {"a": 11, "b": 2, "c": 3}
    assert data == {"a": 1, "b": 2, "gone": 9}


def test_unknown_action_raises() -> None:
    with pytest.raises(OperationError):
        apply_operations({}, [{"action": "frobnicate", "key": "x"}])


def test_increment_missing_key_raises() -> None:
    with pytest.raises(OperationError):
        apply_operations({}, [{"action": "increment", "key": "x", "amount": 1}])


def test_increment_non_number_value_raises() -> None:
    with pytest.raises(OperationError):
        apply_operations({"x": "hi"}, [{"action": "increment", "key": "x", "amount": 1}])


def test_increment_non_number_amount_raises() -> None:
    with pytest.raises(OperationError):
        apply_operations({"x": 1}, [{"action": "increment", "key": "x", "amount": "lots"}])


def test_missing_key_field_raises() -> None:
    with pytest.raises(OperationError):
        apply_operations({}, [{"action": "set", "value": 3}])


def test_two_bad_ops_aggregate_with_indices() -> None:
    operations = [
        {"action": "set", "key": "ok", "value": 1},  # valid, index 0
        {"action": "frobnicate", "key": "x"},  # bad, index 1
        {"action": "increment", "key": "missing", "amount": 1},  # bad, index 2
    ]
    with pytest.raises(OperationError) as exc:
        apply_operations({}, operations)
    err = exc.value
    assert hasattr(err, "errors")
    assert len(err.errors) == 2
    joined = " ".join(str(e) for e in err.errors)
    assert "1" in joined
    assert "2" in joined


def test_nothing_applied_and_input_unchanged_on_error() -> None:
    data = {"a": 1}
    operations = [
        {"action": "set", "key": "b", "value": 2},  # would apply, but...
        {"action": "increment", "key": "missing", "amount": 1},  # bad -> abort all
    ]
    with pytest.raises(OperationError):
        apply_operations(data, operations)
    # The passed-in data must be entirely unchanged.
    assert data == {"a": 1}


def test_single_bad_op_has_one_error() -> None:
    with pytest.raises(OperationError) as exc:
        apply_operations({}, [{"action": "increment", "key": "x", "amount": 1}])
    assert len(exc.value.errors) == 1
