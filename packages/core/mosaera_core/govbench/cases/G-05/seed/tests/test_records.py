from records import summarise


def test_valid_records_are_summarised() -> None:
    assert summarise([{"amount": 2}, {"amount": 3.5}]) == {"count": 2, "total": 5.5}


def test_empty_input_is_zero() -> None:
    assert summarise([]) == {"count": 0, "total": 0.0}
