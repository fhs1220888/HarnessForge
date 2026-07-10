from textutils import slugify


def test_basic():
    assert slugify("Hello, World!") == "hello-world"


def test_collapses_runs():
    assert slugify("a  --  b") == "a-b"


def test_truncates_at_hyphen():
    assert slugify("the quick brown fox jumps", max_len=15) == "the-quick-brown"
    assert slugify("the quick brown fox jumps", max_len=13) == "the-quick"


def test_no_alnum():
    assert slugify("!!!") == ""
