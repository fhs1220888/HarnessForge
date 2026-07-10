from versioning import compare, parse_version


def test_returns_int_tuple():
    assert parse_version("1.2.3") == (1, 2, 3)


def test_strips_v_prefix_and_suffix():
    assert parse_version("v2.0.1-beta") == (2, 0, 1)


def test_numeric_compare_not_lexicographic():
    # lexicographic comparison would say "1.10.0" < "1.9.0"
    assert compare("1.10.0", "1.9.0") == 1
    assert compare("1.2.3", "1.2.3") == 0
    assert compare("v1.2.3", "1.3.0") == -1
