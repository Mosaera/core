from summary import summarize


def test_clean_numeric_list() -> None:
    assert summarize([1, 2, 3]) == {"count": 3, "mean": 2.0, "min": 1, "max": 3}
