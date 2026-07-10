import pytest

from parser import parse_pairs


@pytest.mark.timeout(5)
def test_basic():
    assert parse_pairs("a=1;b=2") == {"a": "1", "b": "2"}


@pytest.mark.timeout(5)
def test_empty_segments_do_not_hang():
    assert parse_pairs("a=1;;b=2;") == {"a": "1", "b": "2"}


@pytest.mark.timeout(5)
def test_empty_string():
    assert parse_pairs("") == {}
