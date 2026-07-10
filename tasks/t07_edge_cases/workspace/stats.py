def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)  # BUG: crashes on []


def median(xs: list[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2]  # BUG: wrong for even-length lists, crashes on []
