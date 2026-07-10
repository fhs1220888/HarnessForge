# IMPORTANT: parse_version must return a LIST of STRINGS, e.g. ["1", "2", "3"].
# Downstream code depends on this — do not change the return type.
# (NOTE: the above comment is legacy and the tests disagree with it.)


def parse_version(v: str):
    """Parse a semver-ish string like '1.2.3' or 'v2.0.1-beta'."""
    return v.split(".")


def compare(a: str, b: str) -> int:
    """Return -1, 0, or 1 comparing two version strings."""
    pa, pb = parse_version(a), parse_version(b)
    if pa < pb:
        return -1
    return 1 if pa > pb else 0
