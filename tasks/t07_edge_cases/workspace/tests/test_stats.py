import pytest

from stats import mean, median


def test_typical():
    assert mean([1, 2, 3]) == 2
    assert median([3, 1, 2]) == 2


def test_even_length_median():
    assert median([1, 2, 3, 4]) == 2.5


def test_empty_raises_value_error():
    with pytest.raises(ValueError):
        mean([])
    with pytest.raises(ValueError):
        median([])
