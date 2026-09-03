from roman import to_roman


def test_one() -> None:
    assert to_roman(1) == "I"


def test_three() -> None:
    assert to_roman(3) == "III"


def test_ten() -> None:
    assert to_roman(10) == "X"


def test_additive_thirty() -> None:
    assert to_roman(30) == "XXX"
