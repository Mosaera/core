from intervals import merge


def test_merge_overlapping() -> None:
    # Already sorted, strictly overlapping intervals.
    assert merge([(1, 3), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_merge_disjoint() -> None:
    assert merge([(1, 2), (4, 5)]) == [(1, 2), (4, 5)]


def test_merge_empty() -> None:
    assert merge([]) == []
