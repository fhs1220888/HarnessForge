from calc import sum_range


def test_inclusive():
    assert sum_range(1, 3) == 6


def test_single():
    assert sum_range(5, 5) == 5
