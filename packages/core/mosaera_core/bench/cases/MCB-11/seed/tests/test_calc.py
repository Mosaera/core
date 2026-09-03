from calc import evaluate


def test_addition_left_to_right() -> None:
    assert evaluate("1 + 2 + 3") == 6


def test_subtraction_left_to_right() -> None:
    assert evaluate("10 - 4 - 1") == 5
