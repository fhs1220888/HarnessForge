import pytest

from pricing import final_price


def test_gold_discount_applied_once():
    assert final_price(100.0, "gold") == pytest.approx(90.0)


def test_standard_no_discount():
    assert final_price(100.0, "standard") == pytest.approx(100.0)


def test_unknown_tier_raises():
    with pytest.raises(KeyError):
        final_price(100.0, "platinum")
