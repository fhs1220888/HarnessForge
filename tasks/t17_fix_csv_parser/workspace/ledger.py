def parse_ledger(path: str) -> list[dict]:
    """Parse a transactions CSV into dicts with amount as float.

    BUG: naive split(',') breaks on quoted commas; doesn't handle the UTF-8
    BOM on the first header cell; leaves '\r' on values from CRLF files.
    """
    rows = []
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    header = lines[0].split(",")
    for line in lines[1:]:
        if not line:
            continue
        values = line.split(",")
        row = dict(zip(header, values))
        row["amount"] = float(row["amount"])
        rows.append(row)
    return rows
