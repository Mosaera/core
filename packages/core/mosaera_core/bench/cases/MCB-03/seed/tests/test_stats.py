from metrics.stats import mean, median, mode


def test_mean() -> None:
    assert mean([1, 2, 3, 4]) == 2.5


def test_median_odd() -> None:
    assert median([3, 1, 2]) == 2


def test_median_even() -> None:
    # An even-length median is the average of the two middle values.
    assert median([1, 2, 3, 4]) == 2.5


def test_mode() -> None:
    assert mode([1, 1, 2, 3]) == 1
