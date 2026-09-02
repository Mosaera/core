from pager import paginate


def test_empty_input_is_empty() -> None:
    assert paginate([], 1, 3) == []


def test_non_positive_page_is_empty() -> None:
    assert paginate([1, 2, 3], 0, 3) == []


def test_non_positive_per_page_is_empty() -> None:
    assert paginate([1, 2, 3], 1, 0) == []


def test_page_beyond_range_is_empty() -> None:
    assert paginate([1, 2, 3], 5, 3) == []
