import random

import converters


def test_spot_checks():
    assert converters.conv_1(0) == 1
    assert converters.conv_120(1) == 240


def test_all_functions_follow_contract():
    rng = random.Random(0)
    for i in range(1, 121):
        fn = getattr(converters, f"conv_{i}")
        x = rng.uniform(-100, 100)
        assert fn(x) == i * x + i, f"conv_{i} violates the contract"
