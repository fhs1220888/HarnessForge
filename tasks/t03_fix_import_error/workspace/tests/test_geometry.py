from geometry import circle_area


def test_area():
    assert abs(circle_area(1.0) - 3.14159265) < 1e-6
