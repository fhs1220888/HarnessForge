import pytest

from flatten import flatten


def test_nested_dicts():
    assert flatten({"a": {"b": {"c": 1}}}) == {"a.b.c": 1}


def test_lists_use_indices():
    assert flatten({"a": [10, {"b": 20}]}) == {"a.0": 10, "a.1.b": 20}


def test_separator_escaping():
    assert flatten({"a.b": 1, "c": {"d.e": 2}}) == {"a\\.b": 1, "c.d\\.e": 2}


def test_empty_containers_are_leaves():
    assert flatten({"a": {}, "b": []}) == {"a": {}, "b": []}


def test_max_depth():
    obj = {"a": {"b": {"c": 1}}}
    assert flatten(obj, max_depth=1) == {"a": {"b": {"c": 1}}}
    assert flatten(obj, max_depth=2) == {"a.b": {"c": 1}}


def test_scalar_raises():
    with pytest.raises(TypeError):
        flatten(42)


def test_custom_separator():
    assert flatten({"a": {"b": 1}}, sep="/") == {"a/b": 1}


def test_top_level_list():
    assert flatten([1, [2, 3]]) == {"0": 1, "1.0": 2, "1.1": 3}
