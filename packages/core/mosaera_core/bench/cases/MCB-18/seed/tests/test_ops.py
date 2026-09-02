from ops import apply_operations


def test_valid_ops_apply_and_do_not_mutate_input() -> None:
    data = {"a": 1, "b": 2, "gone": 9}
    operations = [
        {"action": "set", "key": "c", "value": 3},
        {"action": "delete", "key": "gone"},
        {"action": "increment", "key": "a", "amount": 10},
    ]
    result = apply_operations(data, operations)
    assert result == {"a": 11, "b": 2, "c": 3}
    # The input is untouched.
    assert data == {"a": 1, "b": 2, "gone": 9}
