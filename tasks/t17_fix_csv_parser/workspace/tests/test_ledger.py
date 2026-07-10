from ledger import parse_ledger


def test_parses_all_rows():
    rows = parse_ledger("transactions.csv")
    assert len(rows) == 3


def test_header_has_no_bom():
    rows = parse_ledger("transactions.csv")
    assert "date" in rows[0]  # fails if the BOM sticks to the first header cell


def test_quoted_commas_and_crlf():
    rows = parse_ledger("transactions.csv")
    assert rows[0]["description"] == "coffee, beans and filters"
    assert rows[1]["description"] == "rent"
    # no stray \r from CRLF endings
    assert all(not str(v).endswith("\r") for r in rows for v in r.values())


def test_amounts_are_floats():
    rows = parse_ledger("transactions.csv")
    assert [r["amount"] for r in rows] == [12.5, 900.0, -45.99]
