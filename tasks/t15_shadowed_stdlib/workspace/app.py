import csv
import io


def parse_rows(text: str) -> list[dict[str, str]]:
    """Parse CSV text (with header) into a list of dicts."""
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]
