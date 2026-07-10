def parse_pairs(s: str) -> dict[str, str]:
    """Parse 'k1=v1;k2=v2' into a dict. Skips empty segments."""
    out: dict[str, str] = {}
    i = 0
    while i < len(s):
        j = s.find(";", i)
        if j == -1:
            j = len(s)
        segment = s[i:j]
        if "=" in segment:
            k, v = segment.split("=", 1)
            out[k] = v
        # BUG: when a segment is empty (e.g. ";;"), i never advances past j.
        i = j
    return out
