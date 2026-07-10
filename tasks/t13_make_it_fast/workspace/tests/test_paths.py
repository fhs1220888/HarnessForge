import pytest

from paths import count_paths


def test_small_values():
    assert count_paths(0, 0) == 1
    assert count_paths(1, 1) == 2
    assert count_paths(2, 2) == 6
    assert count_paths(3, 2) == 10


@pytest.mark.timeout(5)
def test_large_value_is_fast():
    assert count_paths(18, 18) == 9075135300


@pytest.mark.timeout(5)
def test_very_large_value():
    assert count_paths(60, 60) == 96614908840363322603893139521372656
