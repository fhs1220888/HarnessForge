from app import parse_rows


def test_parse_basic():
    rows = parse_rows("name,age\nalice,30\nbob,25\n")
    assert rows == [{"name": "alice", "age": "30"}, {"name": "bob", "age": "25"}]


def test_quoted_commas():
    rows = parse_rows('name,notes\nalice,"loves a, b and c"\n')
    assert rows[0]["notes"] == "loves a, b and c"
