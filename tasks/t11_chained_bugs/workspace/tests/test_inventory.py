from report import low_stock, total_value
from store import Store


def test_add_accumulates():
    s = Store()
    s.add_item("apple", 2.0, 3)
    s.add_item("apple", 2.0, 2)
    assert s.items()["apple"]["qty"] == 5


def test_remove_deletes_at_zero():
    s = Store()
    s.add_item("pear", 1.0, 2)
    s.remove_item("pear", 2)
    assert "pear" not in s.items()


def test_total_value():
    s = Store()
    s.add_item("apple", 2.0, 3)
    s.add_item("pear", 1.5, 4)
    assert total_value(s) == 2.0 * 3 + 1.5 * 4


def test_low_stock():
    s = Store()
    s.add_item("apple", 2.0, 1)
    s.add_item("pear", 1.5, 10)
    assert low_stock(s) == ["apple"]
